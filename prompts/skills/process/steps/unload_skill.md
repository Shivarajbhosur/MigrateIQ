---
id: unload
command: unload
aliases: []
description: "Unload baseline data from the database."
handler: unload
session_step: step_5_unload
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "unload <baseline>"
intent_patterns:
  - "unload <baseline>"
  - "unload data for <baseline>"
  - "step 5 for <baseline>"
---

# Unload Skill — Step 5

## When to use
Call this tool when the user asks to unload baseline data from the
database, or "do step 5". Examples:
- `unload P02070-HPPL486P`
- "unload data for that baseline"
- "step 5 for HPPL486P"

## What it does
1. Invokes `unload-BaselineData` PowerShell cmdlet for the baseline.
2. Marks `step_5_unload` complete in the session.
