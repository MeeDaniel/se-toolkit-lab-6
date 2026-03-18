# Task 1: Call an LLM from Code — Implementation Plan

## LLM Provider and Model

**Provider:** Qwen Code API (running on VM)

**Model:** `qwen3-coder-plus`

**Why this choice:**
- 1000 free requests per day (sufficient for development and testing)
- Works from Russia without VPN
- OpenAI-compatible API (easy integration with standard libraries)
- Recommended by the task description

## Architecture Overview

The agent is a simple CLI that:
1. Parses the user question from command-line arguments
2. Loads LLM configuration from `.env.agent.secret`
3. Sends the question to the LLM via HTTP request
4. Parses the LLM response
5. Outputs a structured JSON response to stdout

```
User question (CLI arg) → agent.py → HTTP POST → Qwen API → JSON response → stdout
```

## Components

### 1. Environment Configuration

**File:** `.env.agent.secret`

Contains:
- `LLM_API_KEY` — API key for authentication
- `LLM_API_BASE` — Base URL (e.g., `http://<vm-ip>:8082/v1`)
- `LLM_MODEL` — Model name (`qwen3-coder-plus`)

### 2. Main Agent (`agent.py`)

**Inputs:**
- Single command-line argument: the user question

**Outputs:**
- Single JSON line to stdout: `{"answer": "...", "tool_calls": []}`
- All debug/logging output to stderr

**Key functions:**
- `load_env()` — Load configuration from `.env.agent.secret`
- `call_llm(question: str) -> str` — Send request to LLM API, return answer
- `main()` — Parse args, call LLM, format output, exit

**Error handling:**
- Missing environment file → exit with error message to stderr
- API request failure → exit with error message to stderr
- Timeout (>60s) → subprocess timeout (handled by runner)
- Invalid response → exit with error message to stderr

### 3. Data Flow

```
1. Parse sys.argv[1] → question
2. Load .env.agent.secret → LLM_API_KEY, LLM_API_BASE, LLM_MODEL
3. Build HTTP POST request:
   - URL: {LLM_API_BASE}/chat/completions
   - Headers: Authorization: Bearer {LLM_API_KEY}, Content-Type: application/json
   - Body: {"model": LLM_MODEL, "messages": [{"role": "user", "content": question}]}
4. Send request with timeout
5. Parse response JSON → extract content from choices[0].message.content
6. Output: {"answer": "<content>", "tool_calls": []}
```

## Testing Strategy

**Test file:** `tests/test_agent.py`

**Test case:**
- Run `agent.py "What is 2+2?"` as subprocess
- Parse stdout as JSON
- Assert `answer` field exists and is non-empty string
- Assert `tool_calls` field exists and is an array

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `plans/task-1.md` | Create | This implementation plan |
| `.env.agent.secret` | Create | LLM credentials (gitignored) |
| `agent.py` | Create | Main agent CLI |
| `AGENT.md` | Create | Architecture documentation |
| `tests/test_agent.py` | Create | Regression test |

## Acceptance Criteria Checklist

- [ ] Plan committed before code
- [ ] `agent.py` exists in project root
- [ ] `uv run agent.py "..."` outputs valid JSON with `answer` and `tool_calls`
- [ ] API key in `.env.agent.secret` (not hardcoded)
- [ ] `AGENT.md` documents architecture
- [ ] 1 regression test passes
- [ ] Git workflow: issue, branch, PR with `Closes #...`, partner approval
