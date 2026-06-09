---
id: copy
command: copy
aliases: [copybaseline]
description: "Copy baseline test files from G: drive to C: working directory."
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
---

# Copy Skill — Step 1

## When to use
Call this tool when the user asks to copy baseline files, prepare the
working folder, or "do step 1". Examples:
- `copy P02070-HPPL486P`
- "copy files for that baseline"
- "do step 1 for HPPL486P"

## What it does
1. Copies the baseline folder from G: drive to C: working directory.
2. Creates SYSOUT via `New-Sysout`.
3. Writes per-baseline `.env` via `New-Env`.
4. Copies input files via `Copy-Input`.
5. Marks `step_1_copy` complete in the session.

## Arguments
| Name | Required | Pattern | Example |
|------|----------|---------|---------|
| baseline | yes | `^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$` | `P02070-HPPL486P` |
