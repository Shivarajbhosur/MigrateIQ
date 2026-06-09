---
id: list
command: list
aliases: []
description: "List all known baseline sessions."
handler: list
args: []
intent_patterns:
  - "list"
  - "list sessions"
  - "show all baselines"
---

# List Skill

## When to use
Call this tool when the user asks to list all known baseline sessions.
Examples:
- `list`
- "list sessions"
- "show all baselines"

## What it does
Returns the list of all baseline sessions tracked by `workflows/session_manager.py`.
