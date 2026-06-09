---
id: report
command: report
aliases: []
description: "Generate validation report."
handler: report
session_step: step_7_report
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "report <baseline>"
intent_patterns:
  - "report <baseline>"
  - "generate report for <baseline>"
  - "step 7 for <baseline>"
---

# Report Skill — Step 7

## When to use
Call this tool when the user asks to generate the validation report for a
baseline, or "do step 7". Examples:
- `report P02070-HPPL486P`
- "generate report for that baseline"
- "step 7 for HPPL486P"

## What it does
1. Generates the validation report from the comparison output.
2. Marks `step_7_report` complete in the session.
