#!/usr/bin/env python3
"""Agent CLI - Calls an LLM with tools and returns a structured JSON answer.

Usage:
    uv run agent.py "How do you resolve a merge conflict?"

Output:
    {
      "answer": "...",
      "source": "wiki/git-workflow.md#resolving-merge-conflicts",
      "tool_calls": [...]
    }

All debug output goes to stderr. Only valid JSON goes to stdout.
"""

import json
import os
import sys
from pathlib import Path

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS = 10
PROJECT_ROOT = Path(__file__).parent


def load_env() -> dict[str, str]:
    """Load LLM configuration from .env.agent.secret.

    Returns:
        Dictionary with LLM_API_KEY, LLM_API_BASE, LLM_MODEL

    Raises:
        SystemExit: If environment file is missing or incomplete.
    """
    env_file = Path(".env.agent.secret")
    if not env_file.exists():
        print(f"Error: {env_file} not found", file=sys.stderr)
        print(
            "Copy .env.agent.example to .env.agent.secret and fill in your credentials",
            file=sys.stderr,
        )
        sys.exit(1)

    config = {}
    required_keys = ["LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"]

    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in required_keys:
            config[key] = value

    missing = [k for k in required_keys if k not in config]
    if missing:
        print(f"Error: Missing configuration keys: {missing}", file=sys.stderr)
        sys.exit(1)

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
                "description": "Read a file from the project repository. Use this to read wiki documentation files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root (e.g., wiki/git-workflow.md)"
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files and directories at a given path. Use this to discover available wiki files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative directory path from project root (e.g., wiki)"
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False
                }
            }
        }
    ]


def get_system_prompt() -> str:
    """Return the system prompt for the documentation agent.

    Returns:
        System prompt string
    """
    return """You are a documentation assistant for a software engineering toolkit project.
You have access to a project wiki in the `wiki/` directory.

Available tools:
- list_files(path): List files and directories at a given path
- read_file(path): Read the contents of a file

When answering questions:
1. Use list_files("wiki") to discover available documentation files
2. Use read_file to read specific wiki files that may contain the answer
3. Find the answer in the documentation and cite the source
4. Include the source as "wiki/filename.md#section-anchor" format
5. Once you have the answer, respond with the final answer (no more tool calls)

Important:
- Always include the source field in your final answer
- Maximum 10 tool calls per question
- If you cannot find the answer in the wiki, say so honestly"""


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

TOOLS = {
    "read_file": tool_read_file,
    "list_files": tool_list_files,
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
        # Extract the path argument
        path = args.get("path", "")
        return tool_func(path)
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ---------------------------------------------------------------------------
# LLM Communication
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], config: dict[str, str], tools: list[dict] | None = None) -> dict:
    """Send messages to the LLM and return the response.

    Args:
        messages: List of conversation messages
        config: LLM configuration
        tools: Optional list of tool schemas

    Returns:
        Parsed LLM response dictionary

    Raises:
        SystemExit: If the API request fails.
    """
    api_base = config["LLM_API_BASE"]
    api_key = config["LLM_API_KEY"]
    model = config["LLM_MODEL"]

    url = f"{api_base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload: dict = {
        "model": model,
        "messages": messages,
    }

    if tools:
        payload["tools"] = tools

    print(f"Calling LLM at {url}...", file=sys.stderr)

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        print("Error: LLM request timed out", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"Error: HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Error: Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Agentic Loop
# ---------------------------------------------------------------------------

def run_agentic_loop(question: str, config: dict[str, str]) -> dict:
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
        response_data = call_llm(messages, config, tools=tool_schemas)

        # Extract the assistant message
        try:
            assistant_message = response_data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            print(f"Error: Unexpected API response format: {e}", file=sys.stderr)
            print(f"Response: {response_data}", file=sys.stderr)
            sys.exit(1)

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])

        if not tool_calls:
            # No tool calls - LLM provided final answer
            answer = assistant_message.get("content", "")
            print(f"LLM provided final answer: {answer[:100]}...", file=sys.stderr)

            # Extract source from answer (LLM should mention it)
            # For now, we'll try to parse it from the answer or use a default
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
            tool_calls_log.append({
                "tool": tool_name,
                "args": arguments,
                "result": result,
            })

            # Append tool result to messages
            # Use assistant role with tool output reference for better compatibility
            messages.append({
                "role": "assistant",
                "content": f"[Tool result: {tool_name} returned: {result}]"
            })

            tool_call_count += 1

        # Continue loop - LLM will process tool results and decide next action

    # Max tool calls reached
    print(f"Maximum tool calls ({MAX_TOOL_CALLS}) reached", file=sys.stderr)

    # Make one final call to get the answer
    messages.append({
        "role": "system",
        "content": "Maximum tool calls reached. Please provide your best answer based on the information gathered."
    })

    response_data = call_llm(messages, config, tools=None)

    try:
        assistant_message = response_data["choices"][0]["message"]
        answer = assistant_message.get("content", "")
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
    import re

    # Pattern 1: Full reference with anchor
    match = re.search(r'(wiki/[\w-]+\.md#[\w-]+)', answer)
    if match:
        return match.group(1)

    # Pattern 2: Just file reference
    match = re.search(r'(wiki/[\w-]+\.md)', answer)
    if match:
        return match.group(1)

    return ""


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the agent CLI."""
    # Parse command-line arguments
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py <question>", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Load configuration
    config = load_env()

    # Run agentic loop
    result = run_agentic_loop(question, config)

    # Output structured JSON to stdout
    print(json.dumps(result))


if __name__ == "__main__":
    main()
