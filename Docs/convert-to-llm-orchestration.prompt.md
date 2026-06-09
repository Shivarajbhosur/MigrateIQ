---
description: "Convert validation-agent's hardcoded command routing into an LLM-orchestrated, skill-driven architecture without changing existing functionality."
name: "Convert to LLM-Orchestrated Skill Architecture"
argument-hint: "Run against the validation-agent repo to refactor orchestration only"
agent: "agent"
---

# Convert Validation-Agent to LLM-Orchestrated Skill-Based Architecture

You are a senior Python architect. Work in this repository only:
`C:/Users/shosur/git/validation-agent`

## Objective
Replace hardcoded command routing in `app.py` with an LLM-orchestrated, skill-driven architecture, while preserving every existing behavior, output, and side-effect exactly.

## Business Requirement
- All user input — both command-style (`copy P02070-HPPL494P`) and natural language (`please copy files for P02070`) — must flow through LLM orchestration guided by a master skill file.
- No `if/elif` command routing should remain as the source of orchestration logic.
- The skill file becomes the **single source of truth** for operations, prerequisites, sequencing, tool bindings, and error handling.

---

## Critical Constraints (MUST FOLLOW)
1. **Do NOT change business functionality** or outputs of existing operations.
2. **Reuse existing implementations** for: `copy`, `load`, `branch`, `run`, `unload`, `compare`, `report`, `finalize`, `status`, `reset`, `list`, `help`, `validate`, `reporting`.
3. Only change the **orchestration and routing layers** plus required glue code.
4. Preserve existing **session tracking** and **step status transitions** in `models/session.py` and `workflows/session_manager.py`.
5. Maintain **backward compatibility** for all existing command inputs.
6. Add **natural-language intent handling** through the same skill-driven orchestration.
7. Do not introduce fake tools or rename existing operations unless required for a thin wrapper.
8. If uncertain about behavior, **inspect code first** — never assume.
9. Keep existing PowerShell command bindings exactly as-is (`New-Sysout`, `New-Env`, `Copy-Input`, `load-BaselineData`, `unload-BaselineData`, `compare-x`).

---

## Read and Understand BEFORE Coding
Inspect the following before producing any design or code:
1. `app.py` — current chat entry point and command routing logic (`@cl.on_message`).
2. `agents/` — `DevOpsAgent`, `ScriptRunnerAgent`, `CompareAgent`, `ReportingAgent`, `AnalysisAgent`, `ChatAgent`.
3. `tools/` — `powershell_tools.py`, `devops_tools.py`, `compare_tools.py`, `dotnet_tools.py`, `file_tools.py`.
4. `services/` — `llm_service.py`, `knowledge_base_service.py`, `codebase_service.py`, `cobol_service.py`, `context_builder_service.py`, `ingestion_service.py`.
5. `prompts/` — existing skill files (`chat_skill.md`, `COBOL_TO_CSHARP_SKILL.MD`), `chat_prompts.yaml`, `fix_suggestion.yaml`.
6. `workflows/session_manager.py` and `models/session.py` — step lifecycle, status updates, session JSON format.
7. `config.py` — environment variables, paths, helpers like `get_baseline_group()`, `get_baseline_path()`.
8. How results are formatted and sent to the Chainlit UI (markdown style, headings, status icons).
9. Current error handling, heartbeat patterns, and async/sync boundaries.

---

## Target Architecture

**Before**
```
User input → Python if/elif routing in app.py → direct handler call → response
```

**After**
```
User input → Orchestrator service → LLM (with master skill context + tool definitions)
          → tool selection & execution → response (preserving existing UX)
```

---

## Required Deliverables

### 1. Master Skill File — `prompts/WORKFLOW_ORCHESTRATION_SKILL.md`
The LLM's instruction manual. Must describe:
- **Operation catalog** (all 14 operations) with intent patterns, required parameters, prerequisites, exact tool/function mapping, success response format, and failure handling.
- **Workflow definitions** for `validate` (8 steps) and `reporting` (6 steps) with stop-on-failure semantics.
- **Baseline/program extraction policy** — how to parse `P02070-HPPL494P` (full baseline) and `HPPL494P` (bare program); disambiguation rules.
- **Guardrails** — never push to `master`/`main`/`develop`; never bypass session state; never invent baselines.
- **Response style** — match existing emoji-based markdown formatting (✅ ❌ 🔄 ⏳ 📊 🎫 🌿).

### 2. Orchestrator Service — `services/orchestrator.py`
Must:
- Accept any user message (command or natural language).
- Load master skill content once and inject as system prompt.
- Perform intent + parameter resolution via LLM function calling.
- Execute mapped tools synchronously or asynchronously as needed.
- Support multi-step workflows (`validate`, `reporting`) with deterministic ordering and stop-on-failure.
- Stream/return user-facing messages consistent with existing Chainlit UX (heartbeats, intermediate progress, final summaries).
- Log orchestration decisions (intent matched, tool chosen, parameters, outcome).

### 3. Workflow Tool Wrappers — `tools/workflow_tools.py`
- Expose every existing handler as an LLM-callable tool with **typed parameter schemas**.
- Wrap, do not duplicate — call into `ScriptRunnerAgent`, `DevOpsAgent`, `CompareAgent`, `ReportingAgent`, `SessionManager`.
- Provide a `TOOL_REGISTRY` mapping tool names → callables and a `TOOL_DEFINITIONS` list compatible with the LLM's function-calling format used in `services/llm_service.py`.

### 4. App Routing Update — `app.py`
- Remove the `if command == "copy" / elif command == "load" / ...` block from `@cl.on_message`.
- Route **all** incoming messages to `orchestrator.process(content)`.
- Keep `@cl.on_chat_start` welcome message intact.
- Preserve session-scoped state (`chat_history`, `chat_active_program`, `chat_active_baseline`).

### 5. Minimal Config/Prompt Wiring
- Add only what is strictly needed (e.g., orchestrator system-prompt YAML if LLM service expects it).
- Do not refactor `llm_service.py` beyond what is required to support tool/function calling.

---

## Skill File Content Requirements

### Operation Catalog (every entry must include all fields)
For each of these operations:

| Operation | Source Handler | Step |
|-----------|----------------|------|
| `copy` | `ScriptRunnerAgent.run_step_1_copy` | 1 |
| `load` | `ScriptRunnerAgent.run_step_2_load` | 2 |
| `branch` | `DevOpsAgent.run_step_3a_branch` | 3a |
| `run` | `ScriptRunnerAgent.run_step_3b_run` | 3b |
| `unload` | `ScriptRunnerAgent.run_step_5_unload` | 5 |
| `compare` | `CompareAgent.run_step_6_compare` | 6 |
| `report` | (existing report handler) | 7 |
| `finalize` | `DevOpsAgent` finalize/PR | 8 |
| `validate` | Sequential 1 → 8 | all |
| `reporting` | `ReportingAgent` (6 steps) | reporting |
| `status` | `SessionManager.format_status_display` | utility |
| `reset` | `Session.reset_all` | utility |
| `list` | `SessionManager.list_sessions` | utility |
| `help` | static help text | utility |

Each entry must include:
- **Intent patterns** (command + 2–3 natural-language phrasings)
- **Required parameters** (with types and validation regex for baseline/program names)
- **Prerequisites** (e.g., `load` requires `copy` completed)
- **Tool to call** (exact registry name)
- **Success response template**
- **Failure response template + recovery suggestion**

### Workflow Definitions
- `validate`: stop on first failed step, report which step failed, do not proceed.
- `reporting`: same stop-on-failure semantics for the 6 reporting steps.

### Disambiguation Policy
- If user says only "copy" with no baseline → ask for baseline.
- If only a bare program (`HPPL494P`) is given → use last `chat_active_baseline` if set, else ask.
- Reject inputs that don't match `^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$` for full baselines.

### Guardrails
- Never push to protected branches (`master`, `main`, `develop`).
- Never invent baseline names — always extract from input or session state.
- Never skip steps in `validate` or `reporting` workflows.
- Never expose secrets from `.env` in responses.

---

## Implementation Rules
1. Wrap existing functions; do not duplicate business logic.
2. Tool contracts use **explicit typed parameters** with validation.
3. Robust baseline extraction for both command and natural-language inputs (reuse regex from `agents/chat_agent.py` if suitable).
4. Deterministic execution for ordered workflows.
5. Stop sequence on failure and return clear step-level status.
6. Preserve existing step names (`step_1_copy`, `step_3a_branch`, etc.) used in sessions.
7. Informative logs for orchestration decisions and tool execution.
8. Async/sync boundaries handled safely (use `asyncio.get_event_loop().run_in_executor` where existing handlers do).

---

## Acceptance Criteria
- ✅ `copy P02070-HPPL494P` produces identical output to current behavior.
- ✅ `validate P02070-HPPL494P` runs all 8 steps with same heartbeats and summaries.
- ✅ `reporting P02070-HPPL494P` runs the 6 reporting steps identically.
- ✅ Natural language equivalents work: *"copy files for P02070-HPPL494P"*, *"please run validation on HPPL494P"*.
- ✅ No hardcoded `if command == "..."` orchestration remains in `@cl.on_message`.
- ✅ Adding a new command requires only updating `WORKFLOW_ORCHESTRATION_SKILL.md` + registering one tool — no router edits.
- ✅ Session state and step statuses remain correct.
- ✅ Failure messages are clear and actionable (preserve existing emoji-formatted markdown).
- ✅ All existing PowerShell commands invoked exactly as before.

---

## Testing Requirements
Add or update tests covering:
1. Command intent routing (`copy`, `load`, `branch`, `run`, `unload`, `compare`, `report`, `finalize`, `validate`, `reporting`, `status`, `reset`, `list`, `help`).
2. Natural language intent routing for each operation.
3. Baseline extraction (full + bare program + missing).
4. Tool invocation mapping (correct tool, correct params).
5. `validate` sequence stop-on-failure (mock step 3b failure → no step 4+).
6. `reporting` sequence stop-on-failure.
7. Session state assertions after each operation.

Provide a **concise test matrix** (input → expected tool → expected response shape) and run the suite.

---

## Output Structure (return in this exact order)
1. **Current-state findings** — what the code does today, key call sites, gaps.
2. **Proposed design** — orchestrator flow diagram, tool registry shape, skill file outline.
3. **File-by-file change plan** — exact files, lines/sections to add or replace.
4. **Implementation** — full code for new files, diffs for modified files.
5. **Tests added or updated** — file paths + test matrix.
6. **Validation results** — test run output, manual smoke checks.
7. **Residual risks and follow-ups** — known limitations, future improvements.

---

## Stop Condition
**Produce sections 1–3 ONLY first**, based on actual code inspection.
**Do NOT implement** until the user replies with: `APPROVE IMPLEMENTATION`.
