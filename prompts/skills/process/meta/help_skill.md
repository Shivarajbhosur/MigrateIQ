---
id: help
command: help
aliases: ["?"]
description: "Show command reference."
handler: help
args: []
intent_patterns:
  - "help"
  - "what can you do"
  - "show commands"
---

# Help Skill

## When to use
Call this tool when the user asks for help, command reference, or "what
can you do". Examples:
- `help`
- `?`
- "show commands"

## What it does
Renders the command reference (every operation + its usage) in chat.
