#!/usr/bin/env python3
"""Agent CLI - Calls an LLM and returns a structured JSON answer.

Usage:
    uv run agent.py "What does REST stand for?"

Output:
    {"answer": "Representational State Transfer.", "tool_calls": []}

All debug output goes to stderr. Only valid JSON goes to stdout.
"""

import json
import os
import sys
from pathlib import Path

import httpx


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


def call_llm(question: str, config: dict[str, str]) -> str:
    """Send a question to the LLM and return the answer.

    Args:
        question: The user's question
        config: LLM configuration (API key, base URL, model)

    Returns:
        The LLM's answer as a string

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
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
    }

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

    # Extract answer from OpenAI-compatible response
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        print(f"Error: Unexpected API response format: {e}", file=sys.stderr)
        print(f"Response: {data}", file=sys.stderr)
        sys.exit(1)

    return answer


def main() -> None:
    """Main entry point for the agent CLI."""
    # Parse command-line arguments
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py <question>", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Load configuration
    config = load_env()

    # Call LLM
    answer = call_llm(question, config)

    # Output structured JSON to stdout
    result = {
        "answer": answer,
        "tool_calls": [],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
