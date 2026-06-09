# Split Workflow Orchestration Skill into Per-Step Skill Files (Orchestrator-Worker Pattern)

## Goal

Refactor the **single monolithic** `prompts/WORKFLOW_ORCHESTRATION_SKILL.md` into **one small skill file per step / operation** (microservice-style) and implement the **orchestrator-worker (router + worker) pattern** so the LLM only loads the skill file relevant to the user request — not all 16 at once.

**End state:**
- Tiny router skill (operation IDs + 1-line descriptions only) sent on every message.
- Stage-1 router (deterministic keyword first, LLM fallback) picks ONE skill.
- Stage-2 worker LLM call loads ONLY that skill + its single tool schema.
- Per-message token usage drops ~60–70% on the workflow path.
- Each step file is self-contained (config + messages + PS bindings + LLM "when to use" prose).

## DO NOT Touch (out of scope)

These files MUST remain byte-identical after the refactor:

- `prompts/chat_prompts.yaml`
- `prompts/chat_skill.md`
- `prompts/COBOL_TO_CSHARP_SKILL.MD`
- `prompts/fix_suggestion.yaml`
- `prompts/REPORTING_SKILL.md`
- `prompts/welcome.md`
- All `agents/*.py`
- All `tools/*.py`

ONLY the workflow orchestration skill file and `services/orchestrator.py` loader/dispatch code may change.

## Current State (read these first)

1. `prompts/WORKFLOW_ORCHESTRATION_SKILL.md` — the monolithic file to split.
2. `services/orchestrator.py` — full file. Note: `_load_skill()`, `_parse_operations()`, `agentic_dispatch()`, `_get_skill_system_prompt()`, `_get_tool_schemas()`.
3. `services/llm_service.py` — `chat_with_tools()` method that the worker call reuses.
4. `tools/workflow_tools.py` — handler registry.
5. `app.py` — `@cl.on_message` calls `orchestrator.agentic_dispatch()`.

## Target File Layout

```
prompts/
  skills/
    orchestration/
      _router.md          # Stage-1 router prompt
      _routing_rules.md   # shared guardrails (baseline regex, decision rules)
      _fallback.md        # what to do when routing fails (→ chat)
      _messages.yaml      # UI strings
      _powershell.yaml    # cmdlet catalog
    process/
      steps/
        copy_skill.md
        load_skill.md
        branch_skill.md
        run_skill.md
        unload_skill.md
        compare_skill.md
        report_skill.md
        finalize_skill.md
      workflows/
        validate_skill.md
        reporting_pipeline_skill.md
      meta/
        status_skill.md
        reset_skill.md
        list_skill.md
        help_skill.md
```

Old file `prompts/WORKFLOW_ORCHESTRATION_SKILL.md` becomes a thin README pointing to the new structure (or is deleted in commit 4 once everything works).

## Per-Operation Skill File Format

Each `*_SKILL.md` uses YAML front-matter (machine-readable) + Markdown body (LLM-readable). Everything related to that step lives in ONE file.

Example: `prompts/skills/operations/COPY_SKILL.md`

````markdown
---
id: copy
command: copy
aliases: [copybaseline]
handler: copy
session_step: step_1_copy
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "copy <baseline>"
intent_patterns:
  - "copy <baseline>"
  - "copy files for <baseline>"
  - "step 1 for <baseline>"
messages:
  usage: "Usage: copy <baseline>"
  success: |-
    Step 1: Complete!
    {baseline} ready for validation!
    - Baseline folder copied
    - SYSOUT created
    - .env file placed
    - Input files copied
  failure: "Step 1: Failed\n\n{error}"
powershell_commands:
  - cmdlet: "New-Sysout"
    step: "1b"
  - cmdlet: "New-Env"
    step: "1c"
  - cmdlet: "Copy-Input"
    step: "1d"
---

# Copy Skill — Step 1

## When to use
Call this tool when the user asks to copy baseline files, prepare the
working folder, or "do step 1". Examples:
- `copy P02070-HPPL486P`
- "copy files for that baseline"
- "do step 1 for HPPL486P"

## What it does
1. Creates SYSOUT via `New-Sysout`.
2. Writes per-baseline `.env` via `New-Env`.
3. Copies input files via `Copy-Input`.
4. Marks `step_1_copy = completed`.

## Arguments
| Name | Required | Pattern | Example |
|------|----------|---------|---------|
| baseline | yes | `^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$` | `P02070-HPPL486P` |

## Guardrails
- Refuse if baseline regex does not match; return the usage message.
- Never write outside the configured working directory.
````

Apply the same shape to all 15 operations (copy, load, branch, run, unload, compare, report, finalize, validate, reporting, status, reset, list, help, chat fallback). Preserve every field from the current YAML verbatim — `id`, `command`, `aliases`, `description`, `handler`, `args` (with `validation` regex), `intent_patterns`, `session_step`, `on_failure_action` (e.g. `trigger_analysis` for `run`), `workflow` (for `validate` / `reporting`), `on_failure: stop` (for composites), `is_fallback: true` (for `chat`).

## Orchestrator-Worker Routing (the perf win)

Modify `Orchestrator.agentic_dispatch()` to use a two-stage flow:

### Stage 1 — Router (cheap)

**A. Deterministic pre-router** (free, instant):
- Split the message on whitespace.
- Lowercase the first token.
- Match against `command` + `aliases` from every operation's front-matter.
- On hit: skip to Stage 2 with the matched skill. ZERO LLM tokens spent.

**B. LLM router fallback** (only when deterministic miss):
- System prompt = `_ROUTER_SKILL.md` (operation IDs + 1-line descriptions + rules from `_ROUTING_RULES.md`).
- User prompt = last 10 history turns + current message.
- Constrain response with JSON mode: `{"operation": "<id>", "args": "<extracted>"}`.
- If LLM returns nothing useful, route to `chat` fallback.

### Stage 2 — Worker (only the chosen skill + its single tool)

- System prompt = `_ROUTING_RULES.md` + the ONE chosen `*_SKILL.md` body.
- Tools array = ONLY that operation's tool schema (single-element list).
- Send to `llm_service.chat_with_tools()`.
- Process `tool_calls` exactly as today (whitelisted handler lookup, arg validation, execute).
- Existing handler output / Chainlit messages remain unchanged.

### Multi-step requests

If the router returns multiple operations (e.g., "copy then load P02070-HPPL486P"), loop Stage 2 once per operation in order.

### Composite workflows

`validate` (8 steps) and `reporting` (6 steps) remain server-side composites — the orchestrator iterates through their `workflow:` list and dispatches each sub-operation via the worker path. `on_failure: stop` semantics preserved.

## Loader Changes (`services/orchestrator.py`)

Replace the current single-file loader with:

```python
def _load_skill_file(self, path: Path) -> dict:
    """Parse a Markdown skill file into {meta, body}.
    meta = YAML front-matter (between --- fences). body = full file text.
    """

def _load_operations(self) -> None:
    """Glob prompts/skills/operations/*_SKILL.md.
    Build self._operations (by command), self._skill_bodies (by id),
    self._tool_schemas (by id, single-tool each).
    Fail loudly on duplicate id or YAML parse error.
    """

def _load_orchestration_files(self) -> None:
    """Load _ROUTER_SKILL.md, _ROUTING_RULES.md, _MESSAGES.yaml,
    _POWERSHELL.yaml, _CONFIG.yaml into typed caches.
    """

def _deterministic_route(self, content: str) -> Optional[str]:
    """Keyword/alias match against cached operations. Returns operation id or None."""

async def _llm_route(self, content: str, history: list) -> Optional[str]:
    """LLM router using the tiny _ROUTER_SKILL.md prompt. JSON-mode response."""

async def _llm_invoke_skill(
    self, operation_id: str, content: str, history: list
) -> Any:
    """Stage-2 worker call: single skill body + single tool schema."""
```

All file I/O happens ONCE at startup; per-message dispatch uses cached strings. Existing `_operations`, `_handler_ops`, `_registry` dicts must remain compatible with downstream code paths.

## Behaviour Parity Requirements (HARD)

- All current commands work identically: `copy P02070-HPPL486P`, `do the copy for that baseline`, `step 1 for HPPL486P`, `reporting P02070-HPPL486P`, `validate P02070-HPPL486P`, `list`, `help`, `status P02070-HPPL486P`, etc.
- Case-insensitive baseline matching + `.upper()` normalisation preserved (from the OJ011533 fix).
- Pronoun resolution preserved by passing conversation history into the router.
- `_looks_like_code_question()` delegation to `ChatAgent` unchanged.
- Session state (`session_step` markers) updated exactly as today.
- UI message rendering via `get_message()` unchanged — strings now come from `_MESSAGES.yaml` and per-skill front-matter.
- PowerShell tool invocation unchanged — `_POWERSHELL.yaml` is the new source for the catalog.
- Fallback chains preserved: LLM unavailable → deterministic dispatch → keyword `dispatch()` → chat fallback. Unknown tool name → ignored with warning.
- `ChatAgent` / `ContextBuilderService` / `AnalysisAgent` / `CompareAgent` / `ReportingAgent` paths UNCHANGED.

## Constraints

- **Performance:** worker token count per message must be `≤ 600` tokens (system + tool schema), vs ~1500 today.
- **Whitelist:** worker only sees its one tool. Registry lookup must reject any hallucinated tool name.
- **No new dependencies:** stdlib `re`, `pathlib`, plus existing `yaml`. (Manual `---` front-matter split is preferred over adding `python-frontmatter`.)
- **Fail loud at startup:** duplicate operation IDs, missing required front-matter fields, or YAML parse errors must raise — never silently degrade.
- **No latency regression > 500 ms** per workflow message vs. baseline.

## Suggested Commit Sequence (low-risk, reversible)

1. **Commit 1 — extract config (no behaviour change):**
   Create `prompts/skills/orchestration/_MESSAGES.yaml`, `_POWERSHELL.yaml`, `_CONFIG.yaml`. Move the corresponding blocks out of `WORKFLOW_ORCHESTRATION_SKILL.md`. Update orchestrator to read them from the new locations. App must boot and run identically.

2. **Commit 2 — split operations (no behaviour change):**
   Create `prompts/skills/operations/*_SKILL.md`, one per current YAML entry. Create `_ROUTER_SKILL.md` and `_ROUTING_RULES.md` from the existing routing section + `system_prompt`. Loader globs the folder. Old operation catalog removed from `WORKFLOW_ORCHESTRATION_SKILL.md`. Dispatch still concatenates ALL skill bodies (parity check / safety net).

3. **Commit 3 — orchestrator-worker dispatch (the perf change):**
   Implement Stage-1 deterministic router + Stage-1 LLM router fallback + Stage-2 single-skill worker. Token count must drop. Behaviour parity must hold. Keep the old all-skills concatenation path behind a feature flag for emergency rollback.

4. **Commit 4 — cleanup:**
   Reduce `WORKFLOW_ORCHESTRATION_SKILL.md` to a thin README pointing to the new layout, or delete it. Remove the rollback flag.

Each commit is independently revertable.

## Testing (per commit)

After each commit, verify:

1. `python -c "from services.orchestrator import get_orchestrator; get_orchestrator()"` — no import or startup errors.
2. `python -c "from services.llm_service import get_llm_service"` — no import errors.
3. Zero lint errors in modified files.
4. Manual smoke (must behave EXACTLY as today):
   - `copy P02070-HPPL486P` → Step 1 success message identical.
   - `load P02070-HPPL486P` → Step 2 success message identical.
   - Natural language: "do the copy for baseline P02070-HPPL486P" → routes to copy.
   - Pronoun: after a copy, "now load it" → loads same baseline.
   - Code question: "why does HPPL486P fail on NETSAL?" → routed to chat (ChatAgent + ContextBuilderService unchanged).
   - `reporting P02070-HPPL486P` → full 6-step workflow runs unchanged.
   - `validate P02070-HPPL486P` → full 8-step workflow runs unchanged, stops on failure.
   - `help`, `list`, `status P02070-HPPL486P`, `reset` → unchanged.
   - Case-insensitive: `copy p02070-hppl486p` → normalised and routed.
   - LLM unavailable: keyword `dispatch()` fallback still works.
5. **Token check (commit 3 only):** log `len(system_prompt)` + tool schema bytes per dispatch. Worker call must be ~3× smaller than today.

## Acceptance Criteria

- All existing E2E flows pass.
- Token usage per workflow message drops ≥ 50 %.
- Latency does not regress more than 500 ms per message.
- No protected file modified (chat_prompts.yaml, chat_skill.md, COBOL_TO_CSHARP_SKILL.MD, fix_suggestion.yaml, REPORTING_SKILL.md, welcome.md).
- No handler / agent / tool file modified.

## Out of Scope (do NOT do in this PR)

- Conditional loading of domain skills (`cobol_csharp.md`, `db2_tables.md`, etc.) inside `ChatAgent` — separate concern, separate prompt.
- Caching at the LLM provider level (Azure OpenAI prompt cache) — orthogonal optimisation, verify before/after this PR for accurate measurement.
- New operations or behavioural changes to any existing operation.
- UI / Chainlit changes.

## Pre-Flight Check (recommended before invoking this prompt)

Confirm whether Azure OpenAI **prompt caching** is enabled on the deployment. If it is, the absolute token-cost savings from this refactor will be smaller than the raw token-count drop suggests (cached prefix tokens are billed at a discount). The maintainability and latency benefits still apply.
