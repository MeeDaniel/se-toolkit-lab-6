"""Regression tests for agent.py.

Tests verify that the agent:
1. Produces valid JSON output
2. Has required fields (answer, source, tool_calls)
3. Returns non-empty answers
4. Uses tools correctly (read_file, list_files)
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


# ---------------------------------------------------------------------------
# Task 1 Tests (Basic JSON Output)
# ---------------------------------------------------------------------------

def test_agent_returns_json_with_required_fields():
    """Test that agent.py returns valid JSON with required fields."""
    question = "What is 2+2?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert "answer" in data, "Missing 'answer' field in output"
    assert "source" in data, "Missing 'source' field in output"
    assert "tool_calls" in data, "Missing 'tool_calls' field in output"
    assert isinstance(data["tool_calls"], list), "'tool_calls' should be an array"


def test_agent_returns_non_empty_answer():
    """Test that agent.py returns a non-empty answer."""
    question = "What does REST stand for?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert data.get("answer"), "Answer is empty"
    assert isinstance(data["answer"], str), "Answer should be a string"


# ---------------------------------------------------------------------------
# Task 2 Tests (Tool Calling)
# ---------------------------------------------------------------------------

def test_agent_uses_read_file_for_merge_conflict_question():
    """Test that agent uses read_file tool when asked about merge conflicts.

    The agent should read wiki documentation to find the answer.
    """
    question = "How do you resolve a merge conflict?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert data.get("answer"), "Answer is empty"

    # Check that read_file was used
    tool_calls = data.get("tool_calls", [])
    tools_used = [tc.get("tool") for tc in tool_calls]
    assert "read_file" in tools_used, (
        f"Expected 'read_file' in tool_calls, got: {tools_used}"
    )

    # Check that source references a wiki file about git
    source = data.get("source", "")
    assert "wiki/git" in source and ".md" in source, (
        f"Expected wiki git reference in source, got: {source}"
    )


def test_agent_uses_list_files_for_wiki_discovery():
    """Test that agent uses list_files tool when asked about wiki contents.

    The agent should list files in the wiki directory.
    """
    question = "What files are in the wiki directory?"

    data, error = run_agent(question)

    assert error is None, f"Agent failed: {error}"
    assert data.get("answer"), "Answer is empty"

    # Check that list_files was used
    tool_calls = data.get("tool_calls", [])
    tools_used = [tc.get("tool") for tc in tool_calls]
    assert "list_files" in tools_used, (
        f"Expected 'list_files' in tool_calls, got: {tools_used}"
    )

    # Verify the tool was called with wiki path
    for tc in tool_calls:
        if tc.get("tool") == "list_files":
            args = tc.get("args", {})
            assert args.get("path") == "wiki", (
                f"Expected list_files to be called with path='wiki', got: {args}"
            )


def test_agent_tool_security_rejects_path_traversal():
    """Test that tools reject path traversal attempts (../)."""
    # This test verifies the security check works
    # We run the agent with a question that might trigger path traversal
    question = "Can you read the file ../../etc/passwd?"

    data, error = run_agent(question)

    # Agent should not crash and should handle this gracefully
    assert error is None, f"Agent failed: {error}"
    assert data.get("answer"), "Answer is empty"

    # If any tool was called, verify no path traversal occurred
    for tc in data.get("tool_calls", []):
        args = tc.get("args", {})
        path = args.get("path", "")
        assert ".." not in path, f"Path traversal detected: {path}"
