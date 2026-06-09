# Workflow Orchestration Skill

> **Single source of truth for routing in the Validation Agent.**
>
> This skill file is loaded at startup by `services/orchestrator.py`. The
> orchestrator parses the embedded YAML to build the command catalog, then
> dispatches each user message to the matching tool registered in
> `tools/workflow_tools.py`. To add a new operation, add an entry below and
> register a handler — no changes are required in `app.py`.

---

## Variables

- `{TARGET_LANGUAGE}` — `csharp` | `java` | `python` (from `.env`)
- `{TARGET_LANGUAGE_NAME}` — friendly language name (resolved from `prompts/chat_prompts.yaml`)

These placeholders make the skill file language-agnostic.

---

## Routing Rules

1. The orchestrator splits the incoming message on the first whitespace.
2. The first token is lower-cased and matched against `command` and `aliases`
   in the operation catalog below.
3. On match → the registered handler is invoked with the remaining text as
   `args`. Argument validation is enforced when `args[].validation` regex is
   present.
4. On no match → the message is delegated to the **chat fallback** handler,
   which routes to the existing `ChatAgent` (`agents/chat_agent.py`). This
   preserves natural-language Q&A behaviour exactly as today.
5. The fallback handler is also responsible for pure questions
   (*what / why / how / explain*) and conversational follow-ups.

---

## Guardrails

- **Protected branches** (`master`, `main`, `develop`) must never be pushed
  to. Existing `tools/devops_tools.py` enforces this — handlers must not
  bypass it.
- **Baseline names** must match `^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$` for
  full baselines, e.g. `P02070-HPPL494P` or `P03085-J3021493`.
- **Bare program names** (e.g. `HPPL494P`, `J3021493`) match `^[A-Z]{1,6}\d{2,8}[A-Z]?$`
  and must be resolved to a full baseline by the chat fallback.
- **Secrets** from `.env` must never appear in user-facing messages.
- **Workflow steps** in `validate` and `reporting` stop on first failure.
- **Existing PowerShell bindings** (`New-Sysout`, `New-Env`, `Copy-Input`,
  `load-BaselineData`, `unload-BaselineData`, `compare-x`) are invoked
  unchanged via the existing tool layer.

---

## Operation Catalog

```yaml
operations:

  # ── Step 1 ─────────────────────────────────────────────────────────
  - id: copy
    command: copy
    aliases: ["copybaseline"]
    description: "Copy baseline test files from G: drive to C: working directory."
    handler: copy
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "copy <baseline>"
    intent_patterns:
      - "copy <baseline>"
      - "copy files for <baseline>"
      - "step 1 for <baseline>"
    session_step: step_1_copy

  # ── Step 2 ─────────────────────────────────────────────────────────
  - id: load
    command: load
    aliases: ["loadbaseline"]
    description: "Load baseline data into the database."
    handler: load
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "load <baseline>"
    intent_patterns:
      - "load <baseline>"
      - "load data for <baseline>"
      - "step 2 for <baseline>"
    session_step: step_2_load

  # ── Step 3a ────────────────────────────────────────────────────────
  - id: branch
    command: branch
    aliases: []
    description: "Create Azure DevOps Git branch and pull to local."
    handler: branch
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "branch <baseline>"
    intent_patterns:
      - "branch <baseline>"
      - "create branch for <baseline>"
      - "step 3a for <baseline>"
    session_step: step_3a_branch

  # ── Step 3b ────────────────────────────────────────────────────────
  - id: run
    command: run
    aliases: []
    description: "Run the migrated {TARGET_LANGUAGE_NAME} program (dotnet run)."
    handler: run
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "run <baseline>"
    intent_patterns:
      - "run <baseline>"
      - "execute <baseline>"
      - "step 3b for <baseline>"
    session_step: step_3b_run
    on_failure_action: trigger_analysis  # AnalysisAgent button is rendered

  # ── Step 5 ─────────────────────────────────────────────────────────
  - id: unload
    command: unload
    aliases: []
    description: "Unload baseline data from the database."
    handler: unload
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "unload <baseline>"
    intent_patterns:
      - "unload <baseline>"
      - "unload data for <baseline>"
      - "step 5 for <baseline>"
    session_step: step_5_unload

  # ── Step 6 ─────────────────────────────────────────────────────────
  - id: compare
    command: compare
    aliases: []
    description: "Compare generated output vs expected output (compare-x)."
    handler: compare
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "compare <baseline>"
    intent_patterns:
      - "compare <baseline>"
      - "diff output for <baseline>"
      - "step 6 for <baseline>"
    session_step: step_6_compare

  # ── Step 7 ─────────────────────────────────────────────────────────
  - id: report
    command: report
    aliases: []
    description: "Generate validation report."
    handler: report
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "report <baseline>"
    intent_patterns:
      - "report <baseline>"
      - "generate report for <baseline>"
      - "step 7 for <baseline>"
    session_step: step_7_report

  # ── Step 8 ─────────────────────────────────────────────────────────
  - id: finalize
    command: finalize
    aliases: []
    description: "Finalize: commit, push and create PR."
    handler: finalize
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "finalize <baseline>"
    intent_patterns:
      - "finalize <baseline>"
      - "deliver <baseline>"
      - "step 8 for <baseline>"
    session_step: step_8_finalize

  # ── Workflow: Full validation (steps 1 → 8) ─────────────────────────
  - id: validate
    command: validate
    aliases: []
    description: "Run the full 8-step validation workflow with stop-on-failure."
    handler: validate
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "validate <baseline>"
    intent_patterns:
      - "validate <baseline>"
      - "run validation on <baseline>"
      - "do everything for <baseline>"
    workflow:
      - copy
      - load
      - branch
      - run
      - unload
      - compare
      - report
      - finalize
    on_failure: stop

  # ── Workflow: Reporting task (6 steps) ──────────────────────────────
  - id: reporting
    command: reporting
    aliases: []
    description: "Run the 6-step reporting workflow with stop-on-failure."
    handler: reporting
    args:
      - name: baseline
        required: true
        validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
        usage: "reporting <baseline>"
    intent_patterns:
      - "reporting <baseline>"
      - "run reporting on <baseline>"
    on_failure: stop

  # ── Utility: status ────────────────────────────────────────────────
  - id: status
    command: status
    aliases: []
    description: "Show progress for a baseline session."
    handler: status
    args:
      - name: baseline
        required: true
        usage: "status <baseline>"
    intent_patterns:
      - "status <baseline>"
      - "progress for <baseline>"

  # ── Utility: reset ─────────────────────────────────────────────────
  - id: reset
    command: reset
    aliases: []
    description: "Reset all step statuses for a baseline session."
    handler: reset
    args:
      - name: baseline
        required: true
        usage: "reset <baseline>"
    intent_patterns:
      - "reset <baseline>"
      - "clear progress for <baseline>"

  # ── Utility: list ──────────────────────────────────────────────────
  - id: list
    command: list
    aliases: []
    description: "List all known baseline sessions."
    handler: list
    args: []
    intent_patterns:
      - "list"
      - "list sessions"
      - "show all baselines"

  # ── Utility: help ──────────────────────────────────────────────────
  - id: help
    command: help
    aliases: ["?"]
    description: "Show command reference."
    handler: help
    args: []
    intent_patterns:
      - "help"
      - "what can you do"
      - "show commands"

  # ── Knowledge Q&A ──────────────────────────────────────────────────
  # Queries the knowledge base (COBOL sources, C# codebase, PR fixes)
  # for program-specific questions.  Also used as the fallback handler
  # when no other operation matches in keyword dispatch.
  - id: chat
    command: __fallback__
    aliases: []
    description: >-
      Query the knowledge base for questions about COBOL programs,
      C# translations, field mappings, program logic, DB2 tables,
      or code behaviour.  Use this when the user asks about what a
      program does, how code works, or needs technical details that
      require searching the codebase.
    handler: chat
    args:
      - name: question
        usage: "The user's question to search the knowledge base for"
        required: true
    is_fallback: true

# ───────────────────────────────────────────────────────────────────────
# PowerShell Command Catalog
# ───────────────────────────────────────────────────────────────────────
# Project-specific PowerShell cmdlets invoked by tools/powershell_tools.py.
# Switching client/project = edit this block (no Python changes required).
# Each entry is rendered as: "<cmdlet> <args_template>" with {baseline}
# substituted at call time, then executed via `pwsh -Command "..."`.
powershell_commands:

  - id: new_sysout
    cmdlet: "New-Sysout"
    args_template: "{baseline}"
    step: "1b"
    purpose: "Create SYSOUT output file"

  - id: new_env
    cmdlet: "New-Env"
    args_template: "{baseline}"
    step: "1c"
    purpose: "Create .env file"

  - id: copy_input
    cmdlet: "Copy-Input"
    args_template: "{baseline}"
    step: "1d"
    purpose: "Copy input files to working folder"

  - id: load_baseline_data
    cmdlet: "load-BaselineData"
    args_template: "{baseline}"
    step: "2"
    purpose: "Load baseline data into the database"

  - id: unload_baseline_data
    cmdlet: "unload-BaselineData"
    args_template: "{baseline}"
    step: "5"
    purpose: "Unload baseline data from the database"

# ───────────────────────────────────────────────────────────────────────
# User-Facing Message Templates
# ───────────────────────────────────────────────────────────────────────
# These strings are rendered verbatim into the chat UI by handlers in
# `app.py` via `get_orchestrator().get_message(key, **kwargs)`.
#
# Placeholders use Python `str.format` syntax — `{baseline}`, `{error}` etc.
# Adding / wording changes here require no code edit.
#
# Keys are dot-paths: e.g. "usage.copy" resolves to messages.usage.copy.
messages:

  usage:
    copy:      "⚠️ Usage: `copy <baseline>`"
    load:      "⚠️ Usage: `load <baseline>`"
    branch:    "⚠️ Usage: `branch <baseline>`"
    run:       "⚠️ Usage: `run <baseline>`"
    unload:    "⚠️ Usage: `unload <baseline>`"
    compare:   "⚠️ Usage: `compare <baseline>`"
    report:    "⚠️ Usage: `report <baseline>`"
    finalize:  "⚠️ Usage: `finalize <baseline>`"
    validate:  "⚠️ Usage: `validate <baseline>`"
    reporting: "⚠️ Usage: `reporting <baseline>`"
    status:    "⚠️ Usage: `status <baseline>`"
    reset:     "⚠️ Usage: `reset <baseline>`"

  list:
    empty:  "📋 No sessions found."
    header: "# 📋 All Sessions\n"

  reset:
    success: "🔄 Reset all steps for `{baseline}`"

  not_implemented:
    report:   "🔄 **Step 7: Generate Report**\n\nGenerating report for `{baseline}`...\n\n⚠️ *Not implemented yet*"
    finalize: "🔄 **Step 8: Finalize & Deliver**\n\nFinalizing `{baseline}`...\n\n⚠️ *Not implemented yet*"
    validate: "🚀 **Full Validation**\n\nRunning all steps for `{baseline}`...\n\n⚠️ *Not implemented yet*"

  copy:
    success: |-
      ✅ **Step 1: Complete!**

      `{baseline}` ready for validation!

      **What was done:**
      • ✅ Baseline folder copied
      • ✅ SYSOUT created
      • ✅ .env file placed
      • ✅ Input files copied
    failure: "❌ **Step 1: Failed**\n\n{error}"

  load:
    starting: "🔄 **Step 2: Load to DB**\n\nLoading `{baseline}`...\n\n⏳ Please wait..."
    success:  "✅ **Step 2: Complete**\n\n`{baseline}` loaded to DB!"
    failure:  "❌ **Step 2: Failed**\n\n{error}"

  unload:
    starting: "🔄 **Step 5: Unload from DB**\n\nUnloading `{baseline}`...\n\n⏳ Please wait..."
    success:  "✅ **Step 5: Complete**\n\n`{baseline}` unloaded from DB!"
    failure:  "❌ **Step 5: Failed**\n\n{error}"

  branch:
    starting: "🔄 **Step 3a: Create Branch**\n\nCreating branch for `{baseline}`...\n\n⏳ Please wait..."

  compare:
    word_popup_note: "📄 **Note:** A Word document popup may appear. If it does, please set the security label and save it manually."

# ───────────────────────────────────────────────────────────────────────
# UI assets
# ───────────────────────────────────────────────────────────────────────
# Paths are resolved relative to the project root.  The welcome file is
# read **once at startup** by services/orchestrator.py and cached in
# memory — there is no per-message disk I/O.
ui:
  welcome_file: "prompts/welcome.md"

# ───────────────────────────────────────────────────────────────────────
# LLM-Driven Agentic Orchestration
# ───────────────────────────────────────────────────────────────────────
# Configuration for the fully LLM-driven dispatch pipeline.
# The orchestrator reads this block at startup — zero hardcoded config
# in Python.  Change behaviour here, not in code.
agentic:

  # Maximum tool-call iterations per user message (safety guardrail).
  max_iterations: 10

  # Maximum conversation history turns sent to the LLM.
  # Each turn is one user message + one assistant summary.
  # Higher = better context resolution, but more tokens.
  max_history_turns: 10

  # Tools excluded from LLM tool selection.
  # (chat is now exposed so the LLM can query the knowledge base)
  excluded_tools: []

  # Fallback behaviour when the LLM returns no tool call.
  fallback: chat

  # System prompt sent to the LLM before the skill file content.
  # The LLM reads this + all skill files to understand what tools to call.
  system_prompt: |
    You are a Validation Agent orchestrator for the COBOL-to-C# migration
    validation project.  Your job is to understand the user's request and
    execute the correct operation by calling the appropriate tool.

    CONVERSATION MEMORY:
    You receive the recent conversation history between the user and
    yourself.  Each assistant message in history contains:
    - Which tool was executed and with what arguments
    - The current session state (completed/pending/failed steps)
    - Step-by-step status details for the baseline

    Use conversation history to:
    - Resolve references like "it", "that baseline", "this" → look up the
      last baseline mentioned
    - "now load" / "next step" → infer the baseline from history
    - "do the same for X" → repeat the last operation with a new baseline
    - Answer follow-up questions like "give me a summary", "what happened?",
      "what's the status?" using the session state in history
    - Provide intelligent summaries when asked — cite specific steps,
      baselines, pass/fail results, and ticket numbers from history

    If the user refers to a baseline mentioned earlier, extract it from
    the history and pass it to the tool.  NEVER ask the user to repeat
    a baseline name that already appeared in the conversation.

    FOLLOW-UP QUESTIONS:
    When the user asks about a previous operation (e.g. "give me a
    summary", "what happened?", "what was the result?"), DO NOT call
    any tool.  Respond with a helpful text answer using the execution
    output and session state from the conversation history.  Be
    specific — mention baseline names, step results, timing,
    comparison outcomes, ticket numbers, and report paths from the
    execution output in history.

    KNOWLEDGE QUESTIONS:
    When the user asks about what a program does, how COBOL/C# code
    works, field mappings, DB2 tables, or any technical detail that
    requires searching the codebase — call the "chat" tool with the
    user's question.  The chat tool searches the knowledge base
    (COBOL sources, C# translations, PR fixes) and returns an
    informed answer.

    HOW TO DECIDE (no tool call vs chat tool vs operation tool):
    - "give me a summary of reporting" → TEXT (follow-up, answer
      from execution output in history)
    - "what does HPPL486P do?" → CHAT TOOL (knowledge question)
    - "explain the COBOL logic" → CHAT TOOL (knowledge question)
    - "reporting P02070-HPPL486P" → REPORTING TOOL (operation)
    - "what's the status?" → TEXT if answerable from history,
      otherwise STATUS TOOL

    CRITICAL RULES:
    1. When the user requests ANY operation (copy, load, run, branch,
       unload, compare, report, finalize, validate, reporting, status,
       reset, list, help), you MUST call the corresponding tool.
       NEVER generate a text response instead of calling a tool.
    2. Extract the baseline name (e.g. P02070-HPPL486P) from the user
       message OR from conversation history and pass it as the "args"
       parameter to the tool.
    3. Respond with text (no tool call) ONLY for:
       - Follow-up questions about previous operations that can be
         answered from the execution output in conversation history
       - Greetings and small talk
    4. For questions about programs, code, COBOL, C#, or technical
       details → call the "chat" tool (knowledge base search).
    5. The skill files below describe every operation, its purpose, and
       its arguments.  Use them to decide which tool to call.
    6. If the user asks for multiple operations, call each tool in the
       correct order (one at a time).
    7. Baseline names follow the pattern: P{digits}-{LETTERS}{digits}{optional letter}
       Examples: P02070-HPPL486P, P03085-J3021493, P02003-HPPL043P

  # Tool schema template — auto-generated from operation catalog.
  #   name        <- operation.handler
  #   description <- operation.description
  #   args        <- operation.args[0].usage (if args exist)
  tool_schema:
    arg_parameter_name: "args"
    arg_description_fallback: "Argument for {name}"
```

---

## Notes for Maintainers

- **Add a new operation** → append a new entry to the YAML block above and
  register the handler in `tools/workflow_tools.py` (or `app.py` if the
  handler must touch Chainlit primitives like `cl.Action`).
- **Switch target language** → change `TARGET_LANGUAGE` in `.env` and add the
  matching `prompts/COBOL_TO_<LANG>_SKILL.MD` file. No code changes needed.
- **Disable an operation** → comment out its YAML entry. Existing handler
  code remains untouched.
