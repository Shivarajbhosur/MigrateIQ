# Workflow Routing Rules

> Shared guardrails and decision rules consumed by `services/orchestrator.py`.
> This file is loaded as part of the LLM system prompt alongside every
> per-operation skill file in `process/`.

---

## Variables

- `{TARGET_LANGUAGE}` — `csharp` | `java` | `python` (from `.env`)
- `{TARGET_LANGUAGE_NAME}` — friendly language name (resolved from `prompts/chat_prompts.yaml`)

---

## Routing Rules

1. The orchestrator splits the incoming message on the first whitespace.
2. The first token is lower-cased and matched against `command` and `aliases`
   in the per-operation skill files under `process/`.
3. On match → the registered handler is invoked with the remaining text as
   `args`. Argument validation is enforced when `args[].validation` regex is
   present.
4. On no match → the message is delegated to the **chat fallback** skill
   (`process/meta/chat_fallback_skill.md`), which routes to the existing
   `ChatAgent` (`agents/chat_agent.py`). This preserves natural-language
   Q&A behaviour exactly as today.
5. The fallback handler is also responsible for pure questions
   (*what / why / how / explain*) and conversational follow-ups.

---

## Guardrails

- **Protected branches** (`master`, `main`, `develop`) must never be pushed
  to. Existing `tools/devops_tools.py` enforces this — handlers must not
  bypass it.
- **Baseline names** must match `^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$` for
  full baselines, e.g. `P02070-HPPL494P` or `P03085-J3021493`.
- **Bare program names** (e.g. `HPPL494P`, `J3021493`) match
  `^[A-Z]{1,6}\d{2,8}[A-Z]?$` and must be resolved to a full baseline by
  the chat fallback.
- **Secrets** from `.env` must never appear in user-facing messages.
- **Workflow steps** in `validate` and `reporting` stop on first failure.
- **Existing PowerShell bindings** (`New-Sysout`, `New-Env`, `Copy-Input`,
  `load-BaselineData`, `unload-BaselineData`, `compare-x`) are invoked
  unchanged via the existing tool layer.

---

## Notes for Maintainers

- **Add a new operation** → create a new `*_skill.md` file under the
  appropriate `process/` subfolder (`steps/`, `workflows/`, `meta/`) and
  register the handler in `tools/workflow_tools.py` (or `app.py` if the
  handler must touch Chainlit primitives like `cl.Action`).
- **Switch target language** → change `TARGET_LANGUAGE` in `.env` and add
  the matching `prompts/COBOL_TO_<LANG>_SKILL.MD` file. No code changes
  needed.
- **Disable an operation** → delete or rename its `*_skill.md` file.
  Existing handler code remains untouched.
- **Modify a message template** → edit `_messages.yaml`.
- **Modify a PowerShell binding** → edit `_powershell.yaml`.
- **Tune runtime knobs** (`max_iterations`, `max_history_turns`,
  `system_prompt`, etc.) → edit `_config.yaml`.
