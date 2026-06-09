---
id: chat
command: __fallback__
aliases: []
description: >-
  Query the knowledge base for questions about COBOL programs,
  C# translations, field mappings, program logic, DB2 tables,
  or code behaviour.  Use this when the user asks about what a
  program does, how code works, or needs technical details that
  require searching the codebase.
handler: chat
is_fallback: true
args:
  - name: question
    required: true
    usage: "The user's question to search the knowledge base for"
---

# Chat Fallback Skill

## When to use
This is the catch-all skill. The orchestrator routes here when:
1. No other operation keyword matches the user's message.
2. The user asks a pure knowledge question (what a program does, how code
   works, field mappings, DB2 tables, COBOL ↔ target-language behaviour).
3. The user pastes a code snippet asking for review.

## What it does
Delegates to `agents/chat_agent.py` (`ChatAgent.chat_stream`), which:
1. Loads the relevant COBOL + target-language source files via
   `services/context_builder_service.py`.
2. Applies `chat_skill.md` + `COBOL_TO_<LANG>_SKILL.MD` rules ("snippet
   is broken, real file is truth, no extras, no fabrication").
3. Streams the answer back to the user.

This is the ONLY path that has real source code in the LLM prompt — the
workflow orchestrator never sees source files.
