# Implement LLM-Driven Agentic Orchestration

## Goal

Replace the current regex/keyword-based orchestrator with an LLM-driven agentic orchestrator. The LLM should read skill files as its system prompt, receive registered handlers as "tools", and decide which tool to call based on the user's natural language request.

## Current Architecture (DO NOT break this)

- `services/orchestrator.py` — Keyword/regex dispatcher. Parses YAML from skill files, matches commands, calls handlers.
- `services/llm_service.py` — LLM client (EnsoAI gateway). Has `chat()` and `chat_sync()` methods. Supports GPT-4.1/Azure, GPT-5, Claude, Gemini.
- `prompts/WORKFLOW_ORCHESTRATION_SKILL.md` — Main skill file with YAML defining operations, PS commands, messages, UI config.
- `prompts/REPORTING_SKILL.md` — Reporting workflow skill with 6 steps.
- `tools/workflow_tools.py` — Handler registry (`register_many()`, `get_tool_registry()`).
- `app.py` — Chainlit entry point. Registers handlers, calls `orchestrator.dispatch(content)` from `@cl.on_message`.
- All agents (`agents/*.py`) and tools (`tools/*.py`) remain unchanged.

## What to Implement

### 1. `services/llm_service.py` — Add `chat_with_tools()` method

Add an async method that supports OpenAI function/tool calling:

- Accepts `messages: list`, `tools: list[dict]` (OpenAI tool schema format), `tool_choice: str = "auto"`
- Returns the full response including any `tool_calls` in the assistant message
- Uses the same EnsoAI API endpoint and auth as existing `chat()` method
- Do NOT modify existing `chat()` or `chat_sync()` methods

### 2. `services/orchestrator.py` — Add `agentic_dispatch()` method

Add a new async method to the `Orchestrator` class:

- Reads ALL skill files from `prompts/` directory (`*.md`) and concatenates them as the system prompt
- Builds an OpenAI-format tools array from the handler registry (`get_tool_registry()`) — each handler becomes a tool with name and description
- Sends: `system_prompt` (skill files) + `tools` + `user message` → LLM
- If LLM returns a `tool_call` → execute the matching handler from registry → feed result back to LLM → repeat
- If LLM returns a text response (no tool call) → return it as the final answer
- Loop with max 10 iterations as a safety guardrail
- Keep the existing `dispatch()` method intact — add `agentic_dispatch()` as a NEW method

### 3. `app.py` — Switch to agentic dispatch

In the `@cl.on_message` handler, change `orchestrator.dispatch(content)` to `orchestrator.agentic_dispatch(content)`. ONE line change only.

### 4. Tool schema generation

Create a helper that converts the handler registry dict into OpenAI function-calling tool schemas:

```python
# Each registered handler becomes:
{
    "type": "function",
    "function": {
        "name": "handle_copy",
        "description": "Copy baseline files. Requires baseline name as argument.",
        "parameters": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": "The baseline name, e.g. P02070-HPPL486P"
                }
            },
            "required": ["args"]
        }
    }
}
```

Use the operation descriptions from the skill file YAML to populate the tool descriptions.

## Constraints

- ZERO changes to any handler, agent, or tool file
- Existing functionality must work exactly as before (same UX, same messages, same flow)
- The LLM must read skill files automatically (no manual loading by user)
- Skill files are loaded once at startup and cached
- Add cost controls: max 10 tool-call iterations per user message
- Tool whitelist: only handlers from the registry can be called (no arbitrary function execution)
- Validate baseline format before passing to handlers
- If LLM service is unavailable, fall back to existing keyword-based `dispatch()`

## Files to Read First

Read these files to understand the current code before making changes:

1. `services/orchestrator.py` — Current orchestrator (full file)
2. `services/llm_service.py` — Current LLM service (full file)
3. `app.py` — Current message handler (full file)
4. `tools/workflow_tools.py` — Handler registry
5. `prompts/WORKFLOW_ORCHESTRATION_SKILL.md` — Main skill file
6. `prompts/REPORTING_SKILL.md` — Reporting skill file
7. `config.py` — Configuration

## Testing

After implementation, verify:

1. `python -c "from services.orchestrator import get_orchestrator"` — no import errors
2. `python -c "from services.llm_service import get_llm_service"` — no import errors
3. Check for zero lint errors in modified files
