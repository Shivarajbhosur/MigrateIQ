---
id: status
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
---

# Status Skill

## When to use
Call this tool when the user asks for the progress / status of a baseline
session. Examples:
- `status P02070-HPPL486P`
- "progress for that baseline"

## What it does
Reports per-step status (completed / pending / failed) for the baseline
session, plus any captured failure details.
