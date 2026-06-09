---
id: run
command: run
aliases: []
description: "Run the migrated {TARGET_LANGUAGE_NAME} program (dotnet run)."
handler: run
session_step: step_3b_run
on_failure_action: trigger_analysis
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "run <baseline>"
intent_patterns:
  - "run <baseline>"
  - "execute <baseline>"
  - "step 3b for <baseline>"
---

# Run Skill — Step 3b

## When to use
Call this tool when the user asks to run / execute the migrated
target-language program, or "do step 3b". Examples:
- `run P02070-HPPL486P`
- "execute that baseline"
- "step 3b for HPPL486P"

## What it does
1. Invokes `dotnet run` (or equivalent for the configured target language).
2. Marks `step_3b_run` complete in the session.
3. On failure: the AnalysisAgent action button is rendered so the user can
   trigger root-cause analysis.
