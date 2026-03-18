# Agent Architecture

## Overview

This agent is a CLI tool that connects to an LLM (Large Language Model) and returns structured JSON answers. It forms the foundation for the more advanced agent with tools and agentic loop that will be built in Tasks 2-3.

## LLM Provider

**Provider:** Qwen Code API

**Model:** `qwen3-coder-plus`

**Why Qwen Code:**
- 1000 free requests per day (sufficient for development and testing)
- Works from Russia without VPN
- OpenAI-compatible API (easy integration)
- Strong code understanding capabilities

## Architecture

### Components

1. **CLI Entry Point (`agent.py`)**
   - Parses command-line arguments
   - Loads environment configuration
   - Orchestrates the LLM call
   - Outputs structured JSON

2. **Environment Configuration (`.env.agent.secret`)**
   - Stores LLM credentials securely (gitignored)
   - Contains: `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`

3. **LLM Client**
   - Uses `httpx` for HTTP requests
   - Sends questions to the Qwen API
   - Parses OpenAI-compatible responses

### Data Flow

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────┐
│   User      │────▶│ agent.py │────▶│  Qwen API   │────▶│  LLM     │
│  Question   │     │   CLI    │     │  (on VM)    │     │  Model   │
└─────────────┘     └──────────┘     └─────────────┘     └──────────┘
                         │                                      │
                         │                                      │
                         │◀─────────────────────────────────────┘
                         │          Answer Content
                         │
                         ▼
                  ┌─────────────┐
                  │ JSON Output │
                  │  {answer,   │
                  │ tool_calls} │
                  └─────────────┘
```

### Request/Response Format

**Request to LLM API:**
```json
POST {LLM_API_BASE}/chat/completions
Headers:
  Authorization: Bearer {LLM_API_KEY}
  Content-Type: application/json

Body:
{
  "model": "qwen3-coder-plus",
  "messages": [{"role": "user", "content": "<question>"}]
}
```

**Response from agent.py:**
```json
{
  "answer": "<LLM's answer>",
  "tool_calls": []
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
uv run agent.py "What does REST stand for?"
```

**Output:**
```json
{"answer": "Representational State Transfer.", "tool_calls": []}
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

## Testing

Run the regression test:

```bash
pytest tests/test_agent.py
```

The test verifies:
- Agent produces valid JSON
- `answer` field is present and non-empty
- `tool_calls` field is present and is an array

## Future Work (Tasks 2-3)

In the next tasks, the agent will be extended with:

1. **Tools** - Functions the agent can call (e.g., `read_file`, `query_api`)
2. **Agentic Loop** - Multi-turn reasoning to decide when to use tools
3. **Source Attribution** - Referencing files from the wiki
4. **Enhanced System Prompt** - Domain knowledge about the LMS

## File Structure

```
.
├── agent.py              # Main CLI entry point
├── .env.agent.secret     # LLM credentials (gitignored)
├── AGENT.md              # This documentation
├── plans/
│   └── task-1.md         # Implementation plan
└── tests/
    └── test_agent.py     # Regression tests
```
