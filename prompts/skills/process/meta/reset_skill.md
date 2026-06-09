---
id: reset
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
---

# Reset Skill

## When to use
Call this tool when the user asks to reset / clear the progress for a
baseline session. Examples:
- `reset P02070-HPPL486P`
- "clear progress for that baseline"

## What it does
Resets every step status (`step_1_copy` … `step_8_finalize`) for the
baseline session back to pending. File-system artefacts are NOT deleted.
