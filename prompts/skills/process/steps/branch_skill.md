---
id: branch
command: branch
aliases: []
description: "Create Azure DevOps Git branch and pull to local."
handler: branch
session_step: step_3a_branch
args:
  - name: baseline
    required: true
    validation: '^P\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?$'
    usage: "branch <baseline>"
intent_patterns:
  - "branch <baseline>"
  - "create branch for <baseline>"
  - "step 3a for <baseline>"
---

# Branch Skill — Step 3a

## When to use
Call this tool when the user asks to create the Azure DevOps Git branch
for a baseline, or "do step 3a". Examples:
- `branch P02070-HPPL486P`
- "create branch for that baseline"
- "step 3a for HPPL486P"

## What it does
1. Creates a feature branch in Azure DevOps for the baseline.
2. Pulls the branch to the local working copy.
3. Marks `step_3a_branch` complete in the session.
