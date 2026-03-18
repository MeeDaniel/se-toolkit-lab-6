"""Regression tests for agent.py.

Tests verify that the agent:
1. Produces valid JSON output
2. Has required fields (answer, tool_calls)
3. Returns non-empty answers
"""

import json
import subprocess
import sys
from pathlib import Path


def run_agent(question: str) -> tuple[dict, str | None]:
    """Run agent.py with a question and return parsed output.

    Args:
        question: The question to ask the agent

    Returns:
        Tuple of (parsed JSON dict, error message or None)
    """
    result = subprocess.run(
        [sys.executable, "agent.py", question],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        stderr_preview = result.stderr.strip()[:200] if result.stderr else ""
        return {}, f"Agent exited with code {result.returncode}: {stderr_preview}"

    if not result.stdout.strip():
        return {}, "Agent produced no output"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}, f"Agent output is not valid JSON: {result.stdout[:200]}"

    return data, None


def test_agent_returns_json_with_required_fields():
    """Test that agent.py returns valid JSON with 'answer' and 'tool_calls' fields."""
    question = "What is 2+2?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert "answer" in data, "Missing 'answer' field in output"
    assert "tool_calls" in data, "Missing 'tool_calls' field in output"
    assert isinstance(data["tool_calls"], list), "'tool_calls' should be an array"


def test_agent_returns_non_empty_answer():
    """Test that agent.py returns a non-empty answer."""
    question = "What does REST stand for?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert data.get("answer"), "Answer is empty"
    assert isinstance(data["answer"], str), "Answer should be a string"


def test_agent_tool_calls_is_empty_array():
    """Test that tool_calls is an empty array for Task 1 (no tools yet)."""
    question = "Explain what an API is."

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert data.get("tool_calls") == [], "tool_calls should be empty array in Task 1"
