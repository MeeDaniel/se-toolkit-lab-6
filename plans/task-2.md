# Task 2: The Documentation Agent — Implementation Plan

## Overview

Task 2 extends the agent from Task 1 with **tools** and an **agentic loop**. The agent can now:
1. Call `read_file` to read wiki documentation
2. Call `list_files` to discover available files
3. Loop: send tool calls to LLM → execute tools → feed results back → get final answer

## LLM Provider and Model

**Provider:** Qwen Code API (same as Task 1)
**Model:** `qwen3-coder-plus`

## Tool Definitions

### 1. `read_file`

**Purpose:** Read a file from the project repository.

**Parameters:**
- `path` (string, required): Relative path from project root (e.g., `wiki/git-workflow.md`)

**Returns:** File contents as a string, or error message if file doesn't exist.

**Security:**
- Reject paths containing `../` (path traversal)
- Reject absolute paths
- Only allow paths within project root

**Schema (OpenAI function calling):**
```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a file from the project repository",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Relative path from project root (e.g., wiki/git-workflow.md)"
        }
      },
      "required": ["path"]
    }
  }
}
```

### 2. `list_files`

**Purpose:** List files and directories at a given path.

**Parameters:**
- `path` (string, required): Relative directory path from project root (e.g., `wiki`)

**Returns:** Newline-separated listing of entries.

**Security:**
- Reject paths containing `../` (path traversal)
- Reject absolute paths
- Only allow paths within project root

**Schema:**
```json
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
          "description": "Relative directory path from project root (e.g., wiki)"
        }
      },
      "required": ["path"]
    }
  }
}
```

## Agentic Loop

```
Question → LLM (with tool schemas) → Response
                                     │
                     ┌───────────────┴───────────────┐
                     │                               │
              Has tool_calls?                   No tool_calls
                     │                               │
                   Yes                               │
                     │                               │
                     ▼                               │
            Execute each tool                        │
                     │                               │
                     ▼                               │
            Append results as tool messages          │
                     │                               │
                     ▼                               │
            Loop back to LLM (max 10 calls)          │
                     │                               │
                     └───────────────────────────────┘
                                     │
                                     ▼
                            Extract answer + source
                                     │
                                     ▼
                            Output JSON and exit
```

### Loop Implementation

1. **Initialize** conversation with system prompt + user question
2. **Call LLM** with tool schemas
3. **Check response:**
   - If `tool_calls` present:
     - Execute each tool
     - Append tool results as `{"role": "tool", ...}` messages
     - Increment tool call counter
     - If counter >= 10, stop and use current answer
     - Loop back to step 2
   - If no `tool_calls`:
     - Extract answer from `message.content`
     - Extract source (LLM should provide file reference)
     - Output JSON and exit

### System Prompt Strategy

The system prompt will instruct the LLM to:
1. Use `list_files` to discover wiki files when unsure where to look
2. Use `read_file` to read specific wiki files
3. Always include a `source` field with the file path and section anchor
4. Stop calling tools once the answer is found
5. Never exceed 10 tool calls

**Example system prompt:**
```
You are a documentation assistant. You have access to a project wiki
in the `wiki/` directory.

Available tools:
- list_files(path): List files in a directory
- read_file(path): Read a file's contents

When answering questions:
1. First use list_files("wiki") to discover available documentation
2. Use read_file to read relevant files
3. Find the answer and cite the source as "wiki/filename.md#section-anchor"
4. Return your final answer with the source

Always include the source field in your response.
Maximum 10 tool calls per question.
```

## Path Security

To prevent directory traversal attacks:

```python
def is_safe_path(path: str) -> bool:
    """Check if path is safe (no traversal outside project root)."""
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
```

## Output Format

```json
{
  "answer": "Edit the conflicting file, choose which changes to keep, then stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {
      "tool": "list_files",
      "args": {"path": "wiki"},
      "result": "git-workflow.md\n..."
    },
    {
      "tool": "read_file",
      "args": {"path": "wiki/git-workflow.md"},
      "result": "..."
    }
  ]
}
```

## Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `plans/task-2.md` | Create | This implementation plan |
| `agent.py` | Update | Add tools, agentic loop, system prompt |
| `AGENT.md` | Update | Document tools and agentic loop |
| `tests/test_agent.py` | Update | Add 2 tool-calling regression tests |

## Testing Strategy

**Test 1:** Question about merge conflicts
- Input: `"How do you resolve a merge conflict?"`
- Expected: `read_file` in tool_calls, `wiki/git-workflow.md` in source

**Test 2:** Question about wiki files
- Input: `"What files are in the wiki?"`
- Expected: `list_files` in tool_calls

## Acceptance Criteria Checklist

- [ ] Plan committed before code
- [ ] `read_file` and `list_files` tools implemented
- [ ] Agentic loop executes tool calls
- [ ] `tool_calls` populated in output
- [ ] `source` field correctly identifies wiki section
- [ ] Path security prevents traversal attacks
- [ ] `AGENT.md` documents tools and loop
- [ ] 2 tool-calling regression tests pass
- [ ] Git workflow followed
