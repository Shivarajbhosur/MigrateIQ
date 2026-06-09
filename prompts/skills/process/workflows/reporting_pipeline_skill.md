---
id: reporting
command: reporting
aliases: []
description: "Run the 6-step reporting workflow with stop-on-failure."
handler: reporting
on_failure: stop
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "reporting <baseline>"
intent_patterns:
  - "reporting <baseline>"
  - "run reporting on <baseline>"
---

# Reporting Workflow Skill — 6-step Pipeline

## When to use
Call this tool when the user asks to run the reporting workflow for a
baseline. Examples:
- `reporting P02070-HPPL486P`
- "run reporting on that baseline"

## What it does
Runs the 6-step reporting pipeline defined in `prompts/REPORTING_SKILL.md`
(executed by `agents/reporting_agent.py`). `on_failure: stop` — if any step
fails the pipeline halts and reports the failing step.
