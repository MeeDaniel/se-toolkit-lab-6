#!/usr/bin/env python3
"""CLI agent with tools and agentic loop for answering questions from wiki and backend API."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

# Constants
PROJECT_ROOT = Path(__file__).parent.resolve()
MAX_TOOL_CALLS = 10

# System prompt for the agentic loop
SYSTEM_PROMPT = """You are a documentation and system assistant that answers questions about the project.

You have three tools available:
1. `list_files` - List files in a directory (use for discovering wiki or source files)
2. `read_file` - Read the contents of a file (use for wiki docs or source code)
3. `query_api` - Call the backend API (use for data queries or checking system behavior)

Tool selection guide:
- Wiki questions (how to do X, what files exist) → use `list_files` / `read_file` on wiki/
- System facts (framework, ports, status codes) → use `query_api` or `read_file` on source code
- Data queries (how many items, what score) → use `query_api`
- Bug diagnosis → use `query_api` to reproduce error, then `read_file` to find the bug

When answering questions:
1. Choose the right tool based on the question type
2. Use `list_files` to discover relevant files if needed
3. Use `read_file` to read the content of relevant files
4. Use `query_api` to query the running backend for data or behavior
5. Once you have enough information, provide a final answer

Your final answer should include:
- A clear answer to the question
- If applicable, a source reference in the format: `wiki/filename.md#section-anchor` or `path/to/file.py`

Section anchors are lowercase with hyphens instead of spaces (e.g., `#resolving-merge-conflicts`).

If you cannot find the answer, say so honestly.
"""


def load_config() -> dict[str, str]:
    """Load LLM and backend configuration from environment files."""
    config = {}
    
    # Load LLM config from .env.agent.secret
    llm_env_file = Path(".env.agent.secret")
    if not llm_env_file.exists():
        print(f"Error: {llm_env_file} not found", file=sys.stderr)
        print(
            "Copy .env.agent.example to .env.agent.secret and fill in your credentials",
            file=sys.stderr,
        )
        sys.exit(1)

    for line in llm_env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        config[key] = value

    required_llm = ["LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"]
    missing_llm = [k for k in required_llm if k not in config or not config[k]]
    if missing_llm:
        print(f"Error: Missing required LLM config keys: {missing_llm}", file=sys.stderr)
        sys.exit(1)

    # Load LMS_API_KEY from .env.docker.secret
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
    
    # Also check environment variable directly (for autochecker)
    if "LMS_API_KEY" in os.environ:
        config["LMS_API_KEY"] = os.environ["LMS_API_KEY"]
    
    # Load AGENT_API_BASE_URL from environment or use default
    config["AGENT_API_BASE_URL"] = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002")

    return config


def validate_path(path: str) -> tuple[bool, str]:
    """Validate that a path is safe (no traversal outside project root).
    
    Returns (is_valid, error_message).
    """
    if not path:
        return False, "Path cannot be empty"
    
    if path.startswith("/"):
        return False, "Absolute paths are not allowed"
    
    if ".." in path:
        return False, "Path traversal (..) is not allowed"
    
    # Resolve the full path and ensure it's within project root
    full_path = (PROJECT_ROOT / path).resolve()
    try:
        full_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return False, "Path is outside project directory"
    
    return True, ""


def read_file(path: str) -> str:
    """Read a file from the project repository.
    
    Args:
        path: Relative path from project root
        
    Returns:
        File contents as string, or error message
    """
    is_valid, error = validate_path(path)
    if not is_valid:
        return f"Error: {error}"
    
    file_path = PROJECT_ROOT / path
    
    if not file_path.exists():
        return f"Error: File not found: {path}"
    
    if not file_path.is_file():
        return f"Error: Not a file: {path}"
    
    try:
        return file_path.read_text()
    except Exception as e:
        return f"Error reading file: {e}"


def list_files(path: str) -> str:
    """List files and directories at a given path.

    Args:
        path: Relative directory path from project root

    Returns:
        Newline-separated listing, or error message
    """
    is_valid, error = validate_path(path)
    if not is_valid:
        return f"Error: {error}"

    dir_path = PROJECT_ROOT / path

    if not dir_path.exists():
        return f"Error: Directory not found: {path}"

    if not dir_path.is_dir():
        return f"Error: Not a directory: {path}"

    try:
        entries = sorted(dir_path.iterdir())
        names = [e.name for e in entries]
        return "\n".join(names)
    except Exception as e:
        return f"Error listing directory: {e}"


def query_api(method: str, path: str, body: str | None = None, auth: bool = True, config: dict | None = None) -> str:
    """Call the backend API with optional authentication.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., '/items/')
        body: Optional JSON request body
        auth: Whether to include authentication header (default True)
        config: Configuration dict with LMS_API_KEY and AGENT_API_BASE_URL

    Returns:
        JSON string with status_code and body, or error message
    """
    if config is None:
        config = {}

    api_key = config.get("LMS_API_KEY", "")
    base_url = config.get("AGENT_API_BASE_URL", "http://localhost:42002")

    url = f"{base_url}{path}"
    headers = {
        "Content-Type": "application/json",
    }
    
    if auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    print(f"  Executing query_api({method} {path}, auth={auth})...", file=sys.stderr)

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
            elif method.upper() == "PATCH":
                response = client.patch(url, headers=headers, content=body or "{}")
            else:
                return json.dumps({"error": f"Unsupported method: {method}"})

        result = {
            "status_code": response.status_code,
            "body": response.text,
        }
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# Tool definitions for the LLM
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the project repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from project root (e.g., 'wiki/git.md')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from project root (e.g., 'wiki')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Call the backend API. Use for data queries or checking system behavior. Set auth=false to test unauthenticated access.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, PUT, DELETE, PATCH)"
                    },
                    "path": {
                        "type": "string",
                        "description": "API path (e.g., '/items/', '/analytics/completion-rate')"
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON request body for POST/PUT/PATCH"
                    },
                    "auth": {
                        "type": "boolean",
                        "description": "Whether to include authentication header (default true). Set to false to test unauthenticated access."
                    }
                },
                "required": ["method", "path"]
            }
        }
    }
]

# Map tool names to functions
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "list_files": list_files,
    "query_api": query_api,
}


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
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        print(f"Error: Unexpected API response format: {e}", file=sys.stderr)
        print(f"Full response: {data}", file=sys.stderr)
        sys.exit(1)

    return message


def execute_tool(tool_name: str, args: dict, config: dict | None = None) -> tuple[str, str]:
    """Execute a tool and return (tool_name, result).

    Args:
        tool_name: Name of the tool to execute
        args: Tool arguments
        config: Configuration dict (needed for query_api)

    Returns:
        Tuple of (tool_name, result_string)
    """
    if config is None:
        config = {}

    if tool_name not in TOOL_FUNCTIONS:
        return tool_name, f"Error: Unknown tool: {tool_name}"

    func = TOOL_FUNCTIONS[tool_name]
    
    # query_api needs special handling - it takes method, path, body, auth, config
    if tool_name == "query_api":
        method = args.get("method", "GET")
        path = args.get("path", "")
        body = args.get("body")
        auth = args.get("auth", True)  # Default to True for backward compatibility
        print(f"  Executing {tool_name}({method} {path}, auth={auth})...", file=sys.stderr)
        result = func(method=method, path=path, body=body, auth=auth, config=config)
    else:
        # read_file and list_files take path argument
        path = args.get("path", "")
        print(f"  Executing {tool_name}({path!r})...", file=sys.stderr)
        result = func(path)

    # Truncate very long results
    if len(result) > 10000:
        result = result[:10000] + "\n... (truncated)"

    return tool_name, result


async def run_agentic_loop(question: str, config: dict[str, str]) -> dict:
    """Run the agentic loop to answer a question.
    
    Args:
        question: User's question
        config: LLM configuration
        
    Returns:
        Result dict with answer, source, and tool_calls
    """
    # Initialize conversation with system prompt
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    
    tool_calls_log = []
    tool_call_count = 0
    
    print("Starting agentic loop...", file=sys.stderr)
    
    while tool_call_count < MAX_TOOL_CALLS:
        # Call LLM with current conversation state
        print(f"\n[Round {tool_call_count + 1}] Calling LLM...", file=sys.stderr)
        response = await call_llm(messages, config, tools=TOOLS)
        
        # Check if LLM wants to call tools
        tool_calls = response.get("tool_calls", [])
        
        if not tool_calls:
            # LLM provided final answer
            print("LLM provided final answer", file=sys.stderr)
            answer = response.get("content", "")
            
            # Try to extract source from the answer
            source = extract_source(answer)
            
            return {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }
        
        # Execute tool calls
        for tool_call in tool_calls:
            tool_call_count += 1
            
            # Parse tool call (OpenAI format)
            function = tool_call.get("function", {})
            tool_name = function.get("name", "unknown")
            args_str = function.get("arguments", "{}")
            
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            # Execute the tool
            executed_tool, result = execute_tool(tool_name, args, config)
            path_arg = args.get("path", "")
            
            # Log the tool call
            tool_calls_log.append({
                "tool": executed_tool,
                "args": args,
                "result": result,
            })
            
            # Add tool response to messages for the LLM
            # Use assistant role with tool result context for better compatibility
            messages.append({
                "role": "assistant",
                "content": f"[Tool result: {executed_tool}({path_arg!r})]\n{result}",
            })
        
        # Check if we've hit the limit
        if tool_call_count >= MAX_TOOL_CALLS:
            print(f"Reached max tool calls ({MAX_TOOL_CALLS})", file=sys.stderr)
            break
    
    # If we exit the loop without a final answer, synthesize one
    print("Exiting loop without final answer, synthesizing response...", file=sys.stderr)
    
    # Ask LLM to provide a final answer based on gathered information
    messages.append({
        "role": "user",
        "content": "Please provide a final answer based on the information you've gathered. Include the source file path and section anchor.",
    })
    
    response = await call_llm(messages, config, tools=None)
    answer = response.get("content", "")
    source = extract_source(answer)
    
    return {
        "answer": answer,
        "source": source,
        "tool_calls": tool_calls_log,
    }


def extract_source(answer: str) -> str:
    """Extract source reference from the answer.

    Looks for patterns like:
    - wiki/filename.md#section
    - `wiki/filename.md#section`
    - Source: wiki/filename.md#section
    - backend/app/file.py
    - `backend/app/file.py`
    """
    import re

    # Pattern to match wiki file references with anchors
    pattern = r"`?(wiki/[\w-]+\.md#[\w-]+)`?"
    match = re.search(pattern, answer)

    if match:
        return match.group(1).strip("`")

    # Pattern for Python source files
    py_pattern = r"`?(backend/[\w_/]+\.py)`?"
    match = re.search(py_pattern, answer)
    if match:
        return match.group(1).strip("`")

    # Fallback: try to find just the wiki file path
    file_pattern = r"`?(wiki/[\w-]+\.md)`?"
    match = re.search(file_pattern, answer)
    if match:
        return match.group(1).strip("`")

    return ""


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LLM-powered documentation agent with wiki tools"
    )
    parser.add_argument("question", help="The question to answer")
    args = parser.parse_args()

    config = load_config()
    result = asyncio.run(run_agentic_loop(args.question, config))

    print(json.dumps(result))


if __name__ == "__main__":
    main()
