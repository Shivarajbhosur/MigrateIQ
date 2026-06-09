---
id: compare
command: compare
aliases: []
description: "Compare generated output vs expected output (compare-x)."
handler: compare
session_step: step_6_compare
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "compare <baseline>"
intent_patterns:
  - "compare <baseline>"
  - "diff output for <baseline>"
  - "step 6 for <baseline>"
---

# Compare Skill — Step 6

## When to use
Call this tool when the user asks to compare generated vs expected output
for a baseline, or "do step 6". Examples:
- `compare P02070-HPPL486P`
- "diff output for that baseline"
- "step 6 for HPPL486P"

## What it does
1. Invokes `compare-x` to diff generated output vs expected output.
2. A Word document popup may appear — the user must set the security
   label and save it manually if so.
3. Marks `step_6_compare` complete in the session.
