#!/usr/bin/env python3
"""Agent CLI - Calls an LLM with tools and returns a structured JSON answer.

Usage:
    uv run agent.py "How many items are in the database?"

Output:
    {
      "answer": "...",
      "source": "...",
      "tool_calls": [...]
    }

All debug output goes to stderr. Only valid JSON goes to stdout.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS = 15
PROJECT_ROOT = Path(__file__).parent


def load_env() -> dict[str, str]:
    """Load LLM and LMS configuration from environment files.

    Returns:
        Dictionary with LLM_API_KEY, LLM_API_BASE, LLM_MODEL, LMS_API_KEY, AGENT_API_BASE_URL

    Raises:
        SystemExit: If environment file is missing or incomplete.
    """
    config = {}

    # Load LLM config from .env.agent.secret
    env_file = Path(".env.agent.secret")
    if not env_file.exists():
        print(f"Error: {env_file} not found", file=sys.stderr)
        print(
            "Copy .env.agent.example to .env.agent.secret and fill in your credentials",
            file=sys.stderr,
        )
        sys.exit(1)

    required_llm_keys = ["LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"]

    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in required_llm_keys:
            config[key] = value

    missing = [k for k in required_llm_keys if k not in config]
    if missing:
        print(f"Error: Missing LLM configuration keys: {missing}", file=sys.stderr)
        sys.exit(1)

    # Load LMS API key from .env.docker.secret
    lms_env_file = Path(".env.docker.secret")
    if lms_env_file.exists():
        for line in lms_env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "LMS_API_KEY":
                config["LMS_API_KEY"] = value

    # Also check environment variables (for autochecker)
    if "LMS_API_KEY" not in config:
        config["LMS_API_KEY"] = os.environ.get("LMS_API_KEY", "")

    # Get AGENT_API_BASE_URL from environment or use default
    config["AGENT_API_BASE_URL"] = os.environ.get(
        "AGENT_API_BASE_URL", "http://localhost:42002"
    )

    return config


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def is_safe_path(path: str) -> bool:
    """Check if path is safe (no traversal outside project root).

    Args:
        path: Relative path to check

    Returns:
        True if path is safe, False otherwise
    """
    # Reject absolute paths
    if path.startswith("/") or path.startswith("\\"):
        return False
    # Reject path traversal
    if ".." in path:
        return False
    # Reject Windows drive letters
    if len(path) > 1 and path[1] == ":":
        return False
    return True


def tool_read_file(path: str) -> str:
    """Read a file from the project repository.

    Args:
        path: Relative path from project root (e.g., wiki/git-workflow.md)

    Returns:
        File contents as a string, or error message if file doesn't exist.
    """
    if not is_safe_path(path):
        return f"Error: Unsafe path '{path}'. Path traversal is not allowed."

    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: File '{path}' not found."
    if not full_path.is_file():
        return f"Error: '{path}' is not a file."

    try:
        return full_path.read_text()
    except Exception as e:
        return f"Error reading file: {e}"


def tool_list_files(path: str) -> str:
    """List files and directories at a given path.

    Args:
        path: Relative directory path from project root (e.g., wiki)

    Returns:
        Newline-separated listing of entries, or error message.
    """
    if not is_safe_path(path):
        return f"Error: Unsafe path '{path}'. Path traversal is not allowed."

    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: Directory '{path}' not found."
    if not full_path.is_dir():
        return f"Error: '{path}' is not a directory."

    try:
        entries = sorted([e.name for e in full_path.iterdir()])
        return "\n".join(entries)
    except Exception as e:
        return f"Error listing directory: {e}"


def tool_query_api(
    method: str, path: str, body: str | None = None, auth: bool = True
) -> str:
    """Query the backend API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path (e.g., /items/, /analytics/completion-rate)
        body: JSON request body (optional, for POST/PUT)
        auth: Whether to send authentication header (default True)

    Returns:
        JSON string with status_code and body, or error message.
    """
    api_base = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002")
    lms_api_key = os.environ.get("LMS_API_KEY", "")

    url = f"{api_base}{path}"
    headers = {
        "Content-Type": "application/json",
    }
    if auth and lms_api_key:
        headers["Authorization"] = f"Bearer {lms_api_key}"

    print(f"  Querying API: {method} {url} (auth={auth})", file=sys.stderr)

    try:
        with httpx.Client(timeout=30.0) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            elif method.upper() == "POST":
                response = client.post(url, headers=headers, content=body or "{}")
            elif method.upper() == "PUT":
                response = client.put(url, headers=headers, content=body or "{}")
            elif method.upper() == "DELETE":
                response = client.delete(url, headers=headers)
            else:
                return f"Error: Unsupported method '{method}'"

            result = {
                "status_code": response.status_code,
                "body": response.text,
            }
            return json.dumps(result)
    except httpx.TimeoutException:
        return json.dumps({"error": "API request timed out"})
    except httpx.RequestError as e:
        return json.dumps({"error": f"Request failed: {e}"})


# ---------------------------------------------------------------------------
# Tool Schemas for LLM
# ---------------------------------------------------------------------------


def get_tool_schemas() -> list[dict]:
    """Return the tool schemas for OpenAI-compatible function calling.

    Returns:
        List of tool schema dictionaries
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the project repository. Use this to read wiki documentation or source code files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root (e.g., wiki/git-workflow.md, backend/app/main.py)",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files and directories at a given path. Use this to discover available files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative directory path from project root (e.g., wiki, backend/app/routers)",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_api",
                "description": "Query the backend API. Use this for data queries (how many items), checking status codes, or testing endpoints. Set auth=false to test unauthenticated requests.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "description": "HTTP method (GET, POST, PUT, DELETE)",
                        },
                        "path": {
                            "type": "string",
                            "description": "API path (e.g., /items/, /analytics/completion-rate)",
                        },
                        "body": {
                            "type": "string",
                            "description": "JSON request body (optional, for POST/PUT requests)",
                        },
                        "auth": {
                            "type": "boolean",
                            "description": "Whether to send authentication header (default true). Set to false to test unauthenticated requests.",
                        },
                    },
                    "required": ["method", "path"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def get_system_prompt() -> str:
    """Return the system prompt for the system agent.

    Returns:
        System prompt string
    """
    return """You are a documentation and system assistant for a software engineering toolkit project.

Available tools:
- list_files(path): List files in a directory
- read_file(path): Read a file's contents
- query_api(method, path, body, auth): Query the backend API

When answering questions:
1. For wiki documentation questions → use list_files/read_file on wiki/
2. For source code questions (framework, structure, bugs) → use read_file on backend/
3. For data queries (how many items, scores, analytics) → use query_api with auth=true
4. For status codes or API behavior → use query_api (use auth=false for unauthenticated requests)
5. For bug diagnosis → use query_api to reproduce the error, then read_file to find the bug
6. For listing modules/files → use list_files and summarize from the listing, don't read every file

Bug diagnosis tips:
- Look for common Python errors: TypeError (None comparisons), ZeroDivisionError, KeyError, IndexError
- Check for missing null checks before operations like sorted(), arithmetic, or dictionary access
- Trace the data flow: what happens when inputs are empty, None, or unexpected?
- ALWAYS read the source code file after reproducing a bug - don't just rely on error messages

Important:
- If an API call returns 401, try again with auth=true
- If an API call fails, try a different approach - don't repeat the same failing call
- After 2-3 tool calls, check if you have enough information to answer
- Maximum 15 tool calls per question - be efficient!

Always cite sources for wiki/code questions using "wiki/filename.md#section" or "backend/path.py" format.
For API data queries, the source is the API endpoint.
If you cannot find the answer, say so honestly."""


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

TOOLS = {
    "read_file": tool_read_file,
    "list_files": tool_list_files,
    "query_api": tool_query_api,
}


def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool by name with the given arguments.

    Args:
        tool_name: Name of the tool to execute
        args: Arguments dictionary for the tool

    Returns:
        Tool result as a string
    """
    if tool_name not in TOOLS:
        return f"Error: Unknown tool '{tool_name}'"

    tool_func = TOOLS[tool_name]
    try:
        if tool_name == "query_api":
            return tool_func(
                args.get("method", "GET"),
                args.get("path", ""),
                args.get("body"),
                args.get("auth", True),  # Default to authenticated
            )
        else:
            path = args.get("path", "")
            return tool_func(path)
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ---------------------------------------------------------------------------
# LLM Communication
# ---------------------------------------------------------------------------


async def call_llm(
    messages: list[dict],
    config: dict[str, str],
    tools: list[dict] | None = None,
) -> dict:
    """Call the LLM API and return the response.

    Args:
        messages: List of conversation messages
        config: LLM configuration
        tools: Optional tool definitions for function calling

    Returns:
        Parsed response dict with message and tool_calls
    """
    api_base = config["LLM_API_BASE"]
    api_key = config["LLM_API_KEY"]
    model = config["LLM_MODEL"]

    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"Error: API returned status {response.status_code}", file=sys.stderr)
        print(f"Response: {response.text[:200]}", file=sys.stderr)
        sys.exit(1)

    data = response.json()

    # Handle different API response formats
    # Format 1: OpenAI standard - {"choices": [{"message": {...}}]}
    # Format 2: Direct response - {"role": "...", "content": "...", "tool_calls": [...]}
    try:
        if "choices" in data and isinstance(data["choices"], list):
            message = data["choices"][0]["message"]
        elif "role" in data:
            # Direct response format - return as-is
            message = data
        else:
            print(f"Error: Unexpected API response format", file=sys.stderr)
            print(f"Full response: {data}", file=sys.stderr)
            sys.exit(1)
    except (KeyError, IndexError, TypeError) as e:
        print(f"Error: Unexpected API response format: {e}", file=sys.stderr)
        print(f"Full response: {data}", file=sys.stderr)
        sys.exit(1)

    return message


# ---------------------------------------------------------------------------
# Agentic Loop
# ---------------------------------------------------------------------------


async def run_agentic_loop(question: str, config: dict[str, str]) -> dict:
    """Run the agentic loop: LLM calls → execute tools → feed back → repeat.

    Args:
        question: User's question
        config: LLM configuration

    Returns:
        Dictionary with answer, source, and tool_calls
    """
    # Initialize conversation
    system_prompt = get_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    tool_schemas = get_tool_schemas()
    tool_calls_log: list[dict] = []
    tool_call_count = 0

    while tool_call_count < MAX_TOOL_CALLS:
        # Call LLM with tool schemas
        assistant_message = await call_llm(messages, config, tools=tool_schemas)

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])

        if not tool_calls:
            # No tool calls - LLM provided final answer
            answer = assistant_message.get("content") or ""
            print(f"LLM provided final answer: {answer[:100]}...", file=sys.stderr)

            # Extract source from answer (LLM should mention it)
            source = extract_source_from_answer(answer)

            return {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }

        # Execute tool calls
        print(f"LLM requested {len(tool_calls)} tool call(s)", file=sys.stderr)

        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id", f"call_{tool_call_count}")
            function = tool_call.get("function", {})
            tool_name = function.get("name", "unknown")
            arguments_str = function.get("arguments", "{}")

            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                arguments = {}

            print(f"  Executing {tool_name}({arguments})", file=sys.stderr)

            # Execute the tool
            result = execute_tool(tool_name, arguments)

            # Log the tool call
            tool_calls_log.append(
                {
                    "tool": tool_name,
                    "args": arguments,
                    "result": result,
                }
            )

            # Append tool result to messages
            messages.append(
                {
                    "role": "assistant",
                    "content": f"[Tool result: {tool_name} returned: {result}]",
                }
            )

            tool_call_count += 1

        # Continue loop - LLM will process tool results and decide next action

    # Max tool calls reached
    print(f"Maximum tool calls ({MAX_TOOL_CALLS}) reached", file=sys.stderr)

    # Make one final call to get the answer
    messages.append(
        {
            "role": "system",
            "content": "Maximum tool calls reached. Please provide your best answer based on the information gathered.",
        }
    )

    response_data = await call_llm(messages, config, tools=None)

    try:
        assistant_message = response_data["choices"][0]["message"]
        answer = assistant_message.get("content") or ""
    except (KeyError, IndexError):
        answer = "Error: Could not get final answer from LLM."

    source = extract_source_from_answer(answer)

    return {
        "answer": answer,
        "source": source,
        "tool_calls": tool_calls_log,
    }


def extract_source_from_answer(answer: str) -> str:
    """Try to extract a source reference from the answer.

    Args:
        answer: The LLM's answer text

    Returns:
        Source reference or empty string if not found
    """
    # Look for patterns like wiki/filename.md or wiki/filename.md#section
    # Pattern 1: Full reference with anchor (e.g., "Source: wiki/github.md#protect-a-branch")
    match = re.search(r"(wiki/[\w-]+\.md#[\w-]+)", answer)
    if match:
        return match.group(1)

    # Pattern 2: Just file reference with wiki/ prefix (e.g., "Source: wiki/github.md")
    match = re.search(r"(wiki/[\w-]+\.md)", answer)
    if match:
        return match.group(1)

    # Pattern 3: backend file reference (e.g., "backend/app/main.py")
    match = re.search(r"(backend/[\w/.-]+\.py)", answer)
    if match:
        return match.group(1)

    # Pattern 4: Standalone wiki file mention (e.g., "wiki (github.md)" or "in github.md")
    match = re.search(r"\b([\w-]+\.md)(?:#([\w-]+))?\b", answer)
    if match:
        filename = match.group(1)
        # Only match if it's a known wiki file pattern
        if filename in [
            "github.md",
            "git.md",
            "git-workflow.md",
            "git-vscode.md",
            "ssh.md",
            "docker.md",
            "docker-compose.md",
            "lab.md",
            "api.md",
            "backend.md",
        ]:
            anchor = match.group(2)
            if anchor:
                return f"wiki/{filename}#{anchor}"
            return f"wiki/{filename}"

    return ""


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the agent CLI."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="LLM-powered documentation agent with wiki tools"
    )
    parser.add_argument("question", help="The question to answer")
    args = parser.parse_args()

    # Load configuration
    config = load_env()

    # Export config to environment variables so tools can access them
    for key, value in config.items():
        os.environ[key] = value

    # Run agentic loop
    result = asyncio.run(run_agentic_loop(args.question, config))

    # Output structured JSON to stdout
    print(json.dumps(result))


if __name__ == "__main__":
    main()
