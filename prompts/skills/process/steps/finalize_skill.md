---
id: finalize
command: finalize
aliases: []
description: "Finalize: commit, push and create PR."
handler: finalize
session_step: step_8_finalize
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "finalize <baseline>"
intent_patterns:
  - "finalize <baseline>"
  - "deliver <baseline>"
  - "step 8 for <baseline>"
---

# Finalize Skill — Step 8

## When to use
Call this tool when the user asks to finalize / deliver a baseline (commit,
push, create PR), or "do step 8". Examples:
- `finalize P02070-HPPL486P`
- "deliver that baseline"
- "step 8 for HPPL486P"

## What it does
1. Commits the local changes for the baseline branch.
2. Pushes the branch to Azure DevOps.
3. Creates the Pull Request (respecting protected-branch guardrails in
   `tools/devops_tools.py`).
4. Marks `step_8_finalize` complete in the session.
