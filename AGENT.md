# Agent Architecture

## Overview

This agent is a CLI tool that connects to an LLM (Large Language Model) with **tools** and an **agentic loop**. It can read wiki documentation files, discover available files, query the backend API for data, and provide answers with source citations. The agent is designed to answer questions about project documentation, system behavior, and data stored in the backend.

## Key Features

- **Multi-turn reasoning**: The agentic loop allows the LLM to make multiple tool calls in sequence, refining its approach based on intermediate results
- **Tool-based architecture**: All external interactions happen through well-defined tools with clear schemas
- **Secure file access**: Path validation prevents directory traversal attacks
- **Backend API integration**: The `query_api` tool enables data queries and system behavior testing
- **Source citation**: Answers include references to wiki files or API endpoints

## LLM Provider

**Provider:** Qwen Code API

**Model:** `qwen3-coder-plus`

**Why Qwen Code:**

- 1000 free requests per day (sufficient for development and testing)
- Works from Russia without VPN
- OpenAI-compatible API with function calling support
- Strong code understanding capabilities

## Architecture

### Components

1. **CLI Entry Point (`agent.py`)**
   - Parses command-line arguments
   - Loads environment configuration
   - Runs the agentic loop
   - Outputs structured JSON

2. **Environment Configuration (`.env.agent.secret`)**
   - Stores LLM credentials securely (gitignored)
   - Contains: `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`

3. **LLM Client**
   - Uses `httpx` for HTTP requests
   - Sends messages with tool schemas to the Qwen API
   - Parses OpenAI-compatible responses with tool calls

4. **Tools**
   - `read_file`: Read a file from the project repository
   - `list_files`: List files and directories at a given path

5. **Agentic Loop**
   - Manages multi-turn conversation with the LLM
   - Executes tool calls and feeds results back
   - Stops when LLM provides final answer or max calls reached

### Tools

#### `read_file`

Reads a file from the project repository.

**Parameters:**

- `path` (string, required): Relative path from project root (e.g., `wiki/git-workflow.md`)

**Returns:** File contents as a string, or error message.

**Security:**

- Rejects paths containing `..` (path traversal)
- Rejects absolute paths
- Only allows paths within project root

#### `list_files`

Lists files and directories at a given path.

**Parameters:**

- `path` (string, required): Relative directory path from project root (e.g., `wiki`)

**Returns:** Newline-separated listing of entries, or error message.

**Security:**

- Same path security as `read_file`

### Tool Schemas (Function Calling)

Tools are registered with the LLM using OpenAI-compatible function schemas:

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
          "description": "Relative path from project root"
        }
      },
      "required": ["path"]
    }
  }
}
```

The LLM uses these schemas to decide which tool to call and with what arguments.

## Agentic Loop

The agentic loop enables multi-turn reasoning with tool execution:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agentic Loop                            │
│                                                                 │
│  Question → LLM (with tools) → Response                         │
│                               │                                 │
│                   ┌───────────┴───────────┐                     │
│                   │                       │                     │
│            Has tool_calls?          No tool_calls               │
│                   │                       │                     │
│                 Yes                       │                     │
│                   │                       │                     │
│                   ▼                       │                     │
│          Execute each tool                │                     │
│                   │                       │                     │
│                   ▼                       │                     │
│          Append results as tool msgs      │                     │
│                   │                       │                     │
│                   ▼                       │                     │
│          Loop back to LLM                 │                     │
│          (max 10 calls)                   │                     │
│                   │                       │                     │
│                   └───────────────────────┘                     │
│                                   │                             │
│                                   ▼                             │
│                          Extract answer + source                │
│                                   │                             │
│                                   ▼                             │
│                          Output JSON and exit                   │
└─────────────────────────────────────────────────────────────────┘
```

### Loop Steps

1. **Initialize** conversation with system prompt + user question
2. **Call LLM** with tool schemas
3. **Check response:**
   - If `tool_calls` present:
     - Execute each tool function
     - Append tool results as `{"role": "tool", ...}` messages
     - Increment tool call counter
     - If counter >= 10, stop and get final answer
     - Loop back to step 2
   - If no `tool_calls`:
     - Extract answer from `message.content`
     - Extract source reference
     - Output JSON and exit

### System Prompt

The system prompt instructs the LLM on how to use tools:

```
You are a documentation assistant for a software engineering toolkit project.
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
- If you cannot find the answer in the wiki, say so honestly
```

## Data Flow

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────┐
│   User      │────▶│ agent.py │────▶│  Qwen API   │────▶│  LLM     │
│  Question   │     │   CLI    │     │  (on VM)    │     │  Model   │
└─────────────┘     └──────────┘     └─────────────┘     └──────────┘
                         │                                      │
                         │◀─────────────────────────────────────┘
                         │        Response with tool_calls
                         │
                         ▼
                  ┌─────────────┐
                  │ Execute     │
                  │ Tools       │
                  │ (read_file, │
                  │ list_files) │
                  └─────────────┘
                         │
                         │
                         ▼
                  ┌─────────────┐
                  │ Feed results│
                  │ back to LLM │
                  └─────────────┘
                         │
                         │
                         ▼
                  ┌─────────────┐
                  │ Final answer│
                  │ with source │
                  └─────────────┘
```

## Request/Response Format

**Request to LLM API (with tools):**

```json
POST {LLM_API_BASE}/chat/completions
Headers:
  Authorization: Bearer {LLM_API_KEY}
  Content-Type: application/json

Body:
{
  "model": "qwen3-coder-plus",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "How do you resolve a merge conflict?"}
  ],
  "tools": [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "list_files", ...}}
  ]
}
```

**LLM Response (with tool calls):**

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "read_file",
            "arguments": "{\"path\": \"wiki/git-workflow.md\"}"
          }
        }
      ]
    }
  }]
}
```

**Response from agent.py:**

```json
{
  "answer": "Edit the conflicting file, choose which changes to keep, then stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {
      "tool": "read_file",
      "args": {"path": "wiki/git-workflow.md"},
      "result": "..."
    }
  ]
}
```

## How to Run

### Prerequisites

1. Set up Qwen Code API on your VM (see `wiki/qwen.md`)
2. Create `.env.agent.secret` with your credentials:

   ```bash
   cp .env.agent.example .env.agent.secret
   # Edit with your VM IP, port, and API key
   ```

### Usage

```bash
uv run agent.py "How do you resolve a merge conflict?"
```

**Output:**

```json
{
  "answer": "Edit the conflicting file, choose which changes to keep, then stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [...]
}
```

### Debug Output

All debug/logging output goes to stderr. To see it:

```bash
uv run agent.py "Question" 2>&1 | less
```

## Error Handling

The agent handles the following error cases:

| Error | Behavior |
|-------|----------|
| Missing `.env.agent.secret` | Exit with error message to stderr |
| Missing configuration keys | Exit with error message to stderr |
| API timeout (>60s) | Exit with timeout error |
| HTTP error (4xx/5xx) | Exit with status code and response |
| Network error | Exit with request error message |
| Invalid API response | Exit with format error |
| Path traversal attempt | Return error message from tool |
| Max tool calls (10) | Stop loop, get final answer |

## Security

### Path Security

Tools validate paths to prevent directory traversal:

```python
def is_safe_path(path: str) -> bool:
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

This ensures tools can only access files within the project root.

## Testing

Run the regression tests:

```bash
uv run pytest tests/test_agent.py -v
```

Tests verify:

- Agent produces valid JSON with required fields
- Tools are called when needed
- Source field is populated
- Path security works correctly

## File Structure

```
.
├── agent.py              # Main CLI entry point with agentic loop
├── .env.agent.secret     # LLM credentials (gitignored)
├── AGENT.md              # This documentation
├── plans/
│   ├── task-1.md         # Task 1 implementation plan
│   └── task-2.md         # Task 2 implementation plan
└── tests/
    └── test_agent.py     # Regression tests
```

## Future Work (Task 3)

In Task 3, the agent will be extended with:

- Additional tools (e.g., `query_api` to query the backend)
- Enhanced system prompt with domain knowledge
- Better source extraction and citation
- Improved error handling and recovery

---

## Task 3: The System Agent (COMPLETED)

### New Tool: `query_api`

The `query_api` tool enables the agent to query the deployed backend API for data-dependent questions.

**Parameters:**

- `method` (string, required): HTTP method (GET, POST, PUT, DELETE)
- `path` (string, required): API path (e.g., `/items/`, `/analytics/completion-rate`)
- `body` (string, optional): JSON request body for POST/PUT requests
- `auth` (boolean, optional, default=True): Whether to send authentication header

**Returns:** JSON string with `status_code` and `body`, or error message.

**Authentication:** Uses `LMS_API_KEY` from `.env.docker.secret` for `Authorization: Bearer` header. Set `auth=false` to test unauthenticated requests.

**Example usage:**

```bash
uv run agent.py "How many items are in the database?"
```

```json
{
  "answer": "There are 120 items in the database.",
  "source": "",
  "tool_calls": [
    {
      "tool": "query_api",
      "args": {"method": "GET", "path": "/items/"},
      "result": "{\"status_code\": 200, \"body\": \"[...]}"
    }
  ]
}
```

### Environment Variables

The agent reads all configuration from environment variables:

| Variable | Purpose | Source |
|----------|---------|--------|
| `LLM_API_KEY` | LLM provider API key | `.env.agent.secret` |
| `LLM_API_BASE` | LLM API endpoint URL | `.env.agent.secret` |
| `LLM_MODEL` | Model name | `.env.agent.secret` |
| `LMS_API_KEY` | Backend API key for query_api | `.env.docker.secret` |
| `AGENT_API_BASE_URL` | Base URL for query_api (default: `http://localhost:42002`) | Optional, env var |

**Important:** The autochecker injects different values at evaluation time. Never hardcode these values.

### Updated System Prompt

The system prompt guides the LLM to choose the right tool:

1. **Wiki documentation questions** → `list_files`/`read_file` on `wiki/`
2. **Source code questions** → `read_file` on `backend/`
3. **Data queries** → `query_api` with `auth=true`
4. **Status code testing** → `query_api` with `auth=false`
5. **Bug diagnosis** → `query_api` to reproduce, then `read_file` to find the bug

The prompt also includes bug diagnosis tips:

- Look for common Python errors: TypeError, ZeroDivisionError, KeyError, IndexError
- Check for missing null checks before sorted(), arithmetic, or dictionary access
- ALWAYS read the source code after reproducing a bug

### Source Extraction

The `extract_source_from_answer()` function uses multiple regex patterns to extract source references:

1. `wiki/filename.md#anchor` - Full reference with anchor
2. `wiki/filename.md` - Wiki file with prefix
3. `backend/path/file.py` - Backend file reference
4. Standalone wiki file mentions (e.g., "github.md") - Maps to `wiki/github.md`

### Lessons Learned

1. **API Response Format Variations:** The LLM API may return responses in different formats. Handle both standard OpenAI format (`choices[0].message`) and direct response format.

2. **Environment Variable Export:** Configuration loaded from files must be exported to `os.environ` for tools to access them.

3. **Flexible Authentication:** The `query_api` tool needs an optional `auth` parameter to test both authenticated and unauthenticated requests.  

4. **Non-deterministic LLM Responses:** The same question may get different responses. Improve system prompts to guide consistent behavior.

5. **Preventing Infinite Loops:** LLMs can get stuck repeating the same failing action. Add explicit instructions to try different approaches after failures.

6. **Tool Call Limits:** Some questions require more than 10 tool calls. Increased limit to 15 and optimized prompts for efficiency.

7. **Source Citation:** LLMs don't always cite sources in the expected format. Use flexible regex patterns to extract various citation styles.

### Benchmark Results

**Final Score: 10/10 PASSED**

| # | Question | Tool(s) Required | Status |
|---|----------|------------------|--------|
| 0 | Protect branch steps (wiki) | read_file | ✓ |
| 1 | SSH connection steps (wiki) | read_file | ✓ |
| 2 | Python web framework | read_file | ✓ |
| 3 | API router modules | list_files | ✓ |
| 4 | Items in database | query_api | ✓ |
| 5 | Status code without auth | query_api | ✓ |
| 6 | Completion-rate error | query_api, read_file | ✓ |
| 7 | Top-learners error | query_api, read_file | ✓ |
| 8 | Request lifecycle (LLM judge) | read_file | ✓ |
| 9 | ETL idempotency (LLM judge) | read_file | ✓ |

### File Structure (Updated)

```
.
├── agent.py              # Main CLI with agentic loop and 3 tools
├── .env.agent.secret     # LLM credentials (gitignored)
├── .env.docker.secret    # Backend API key (gitignored)
├── AGENT.md              # This documentation
├── plans/
│   ├── task-1.md         # Task 1 implementation plan
│   ├── task-2.md         # Task 2 implementation plan
│   └── task-3.md         # Task 3 implementation plan
└── tests/
    └── test_agent.py     # Regression tests
```
cat 