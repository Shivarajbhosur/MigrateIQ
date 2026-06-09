---
id: load
command: load
aliases: [loadbaseline]
description: "Load baseline data into the database."
handler: load
session_step: step_2_load
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "load <baseline>"
intent_patterns:
  - "load <baseline>"
  - "load data for <baseline>"
  - "step 2 for <baseline>"
---

# Load Skill — Step 2

## When to use
Call this tool when the user asks to load baseline data into the database,
or "do step 2". Examples:
- `load P02070-HPPL486P`
- "load data for that baseline"
- "step 2 for HPPL486P"

## What it does
1. Invokes `load-BaselineData` PowerShell cmdlet for the baseline.
2. Marks `step_2_load` complete in the session.
