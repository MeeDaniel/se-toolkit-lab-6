# Task 3: The System Agent — Implementation Plan

## Overview

Task 3 extends the Documentation Agent (Task 2) with a new tool `query_api` that can query the deployed backend API. This enables the agent to answer:
1. **Static system facts** — framework, ports, status codes (from source code or API)
2. **Data-dependent queries** — item count, scores, analytics (from live API)
3. **Bug diagnosis** — query API, get error, read source code to explain

## LLM Provider and Model

**Provider:** Qwen Code API (same as Tasks 1-2)
**Model:** `qwen3-coder-plus`

## New Tool: `query_api`

### Purpose

Call the deployed backend API to fetch data or test endpoints.

### Parameters

- `method` (string, required): HTTP method (GET, POST, PUT, DELETE, etc.)
- `path` (string, required): API path (e.g., `/items/`, `/analytics/completion-rate`)
- `body` (string, optional): JSON request body for POST/PUT requests

### Returns

JSON string with:
- `status_code`: HTTP status code
- `body`: Response body (parsed JSON or text)
- `error`: Error message if request failed

### Authentication

Uses `LMS_API_KEY` from `.env.docker.secret` for `Authorization: Bearer` header.

### Schema (OpenAI function calling)

```json
{
  "type": "function",
  "function": {
    "name": "query_api",
    "description": "Query the backend API. Use for data queries, checking status codes, or testing endpoints.",
    "parameters": {
      "type": "object",
      "properties": {
        "method": {
          "type": "string",
          "description": "HTTP method (GET, POST, PUT, DELETE)"
        },
        "path": {
          "type": "string",
          "description": "API path (e.g., /items/, /analytics/completion-rate)"
        },
        "body": {
          "type": "string",
          "description": "JSON request body (optional, for POST/PUT)"
        }
      },
      "required": ["method", "path"],
      "additionalProperties": false
    }
  }
}
```

### Implementation

```python
def tool_query_api(method: str, path: str, body: str | None = None) -> str:
    """Query the backend API."""
    api_base = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002")
    lms_api_key = os.environ.get("LMS_API_KEY", "")
    
    url = f"{api_base}{path}"
    headers = {
        "Authorization": f"Bearer {lms_api_key}",
        "Content-Type": "application/json",
    }
    
    # Send request with httpx
    # Return JSON with status_code and body
```

## Environment Variables

The agent reads all configuration from environment variables:

| Variable | Purpose | Source |
|----------|---------|--------|
| `LLM_API_KEY` | LLM provider API key | `.env.agent.secret` |
| `LLM_API_BASE` | LLM API endpoint URL | `.env.agent.secret` |
| `LLM_MODEL` | Model name | `.env.agent.secret` |
| `LMS_API_KEY` | Backend API key for query_api | `.env.docker.secret` |
| `AGENT_API_BASE_URL` | Base URL for query_api (default: `http://localhost:42002`) | Optional |

**Important:** The autochecker injects different values at evaluation time. Never hardcode these values.

## Updated System Prompt

The system prompt must guide the LLM to choose the right tool:

```
You are a documentation and system assistant for a software engineering toolkit project.

Available tools:
- list_files(path): List files in a directory
- read_file(path): Read a file's contents
- query_api(method, path, body): Query the backend API

When answering questions:
1. For wiki documentation questions → use list_files/read_file
2. For source code questions (framework, structure) → use read_file on backend/
3. For data queries (how many items, scores) → use query_api
4. For status codes or API behavior → use query_api
5. For bug diagnosis → use query_api to reproduce, then read_file to find the bug

Always cite sources for wiki/code questions.
Maximum 10 tool calls per question.
```

## Agentic Loop

The loop remains the same as Task 2:
1. Call LLM with tool schemas
2. If tool_calls → execute tools, append results, loop
3. If no tool_calls → extract answer and source, return JSON

The only change is adding `query_api` to the tool schemas.

## Output Format

```json
{
  "answer": "There are 120 items in the database.",
  "source": "",  // Optional for API queries
  "tool_calls": [
    {
      "tool": "query_api",
      "args": {"method": "GET", "path": "/items/"},
      "result": "{\"status_code\": 200, \"body\": [...]}"
    }
  ]
}
```

## Benchmark Questions

The `run_eval.py` script tests 10 questions:

| # | Question | Expected Tool | Answer |
|---|----------|---------------|--------|
| 0 | Protect branch steps (wiki) | read_file | branch, protect |
| 1 | SSH connection steps (wiki) | read_file | ssh, key, connect |
| 2 | Python web framework | read_file | FastAPI |
| 3 | API router modules | list_files | items, interactions, analytics, pipeline |
| 4 | Items in database | query_api | number > 0 |
| 5 | Status code without auth | query_api | 401 or 403 |
| 6 | Completion-rate error | query_api + read_file | ZeroDivisionError |
| 7 | Top-learners error | query_api + read_file | TypeError/None |
| 8 | Request lifecycle (LLM judge) | read_file | 4+ hops |
| 9 | ETL idempotency (LLM judge) | read_file | external_id check |

## Iteration Strategy

1. **First run:** Run `run_eval.py` and note failures
2. **For each failure:**
   - Check if wrong tool was used → improve system prompt
   - Check if tool returned error → fix tool implementation
   - Check if answer phrasing doesn't match keywords → adjust prompt
3. **Re-run** until all 10 pass

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `plans/task-3.md` | Create | This implementation plan |
| `agent.py` | Update | Add query_api tool, update system prompt |
| `.env.docker.secret` | Read | LMS_API_KEY for authentication |
| `AGENT.md` | Update | Document query_api and lessons learned |
| `tests/test_agent.py` | Update | Add 2 system agent regression tests |

## Acceptance Criteria Checklist

- [ ] Plan committed before code
- [ ] `query_api` tool implemented with authentication
- [ ] Agent reads all config from environment variables
- [ ] System prompt updated for wiki vs API vs code questions
- [ ] `run_eval.py` passes all 10 questions
- [ ] `AGENT.md` documents architecture (200+ words)
- [ ] 2 system agent regression tests pass
- [ ] Autochecker bot benchmark passes
- [ ] Git workflow followed

## Initial Benchmark Score

*To be filled after first run of `run_eval.py`*

## Iteration Log

*To be filled as we fix failures*
