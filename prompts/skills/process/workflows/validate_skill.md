---
id: validate
command: validate
aliases: []
description: "Run the full 8-step validation workflow with stop-on-failure."
handler: validate
on_failure: stop
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
---

# Validate Workflow Skill — Full 8-step Pipeline

## When to use
Call this tool when the user asks to run the full validation pipeline for a
baseline, or "do everything". Examples:
- `validate P02070-HPPL486P`
- "run validation on that baseline"
- "do everything for HPPL486P"

## What it does
Runs all 8 steps in order, stopping on first failure:
1. `copy` — Step 1
2. `load` — Step 2
3. `branch` — Step 3a
4. `run` — Step 3b
5. `unload` — Step 5
6. `compare` — Step 6
7. `report` — Step 7
8. `finalize` — Step 8

`on_failure: stop` — if any step fails the pipeline halts and reports the
failing step. The session retains every completed step so the user can
resume manually.
