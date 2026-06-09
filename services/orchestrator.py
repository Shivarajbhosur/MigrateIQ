"""
Orchestrator Service
====================

Skill-driven dispatcher that replaces the hardcoded ``if/elif`` command
routing previously in ``app.py``.

Flow per incoming message
-------------------------
1.  At startup, ``prompts/WORKFLOW_ORCHESTRATION_SKILL.md`` is parsed.  The
    embedded YAML block describes every supported operation: command keyword,
    aliases, handler name, argument schema, validation regex, etc.
2.  When ``dispatch(content)`` is called, the orchestrator:
    a. Splits ``content`` on the first whitespace.
    b. Looks up the first token (case-insensitive) in the operation catalog.
    c. On match → validates arguments against the regex, then invokes the
       registered handler from :mod:`tools.workflow_tools`.
    d. On no match (or empty input) → invokes the **fallback** handler
       (the existing ``ChatAgent`` route).  Natural-language Q&A behaviour
       is preserved exactly as today.

Important properties
--------------------
* The orchestrator has **zero hard-coded command names**.  Adding a new
  command requires only a new entry in the skill file plus a handler
  registration — no edits here.
* Existing handlers (``handle_copy``, ``handle_validate``, …) are reused
  verbatim; this module never touches Chainlit primitives.
* Failures are caught and surfaced through Chainlit by the handlers
  themselves, matching today's UX.  The orchestrator only catches truly
  unexpected exceptions to avoid crashing the chat loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

import config
from tools.workflow_tools import get_tool_registry
from utils.logger import get_logger


logger = get_logger("orchestrator")


# Full baseline name, e.g. "P02070-HPPL494P" or "P03085-J3021493".
# Mirrors the pattern used in agents/chat_agent.py so NL detection stays
# consistent project-wide. Case-insensitive so user typos like
# "p02070-hppl494p" or "Oj011533" still trigger source-aware routing;
# callers normalise the captured name to upper-case before any lookup.
#
# NOTE: These three module-level regexes are *defaults*. The Orchestrator
# overrides them at startup from
# ``prompts/skills/orchestration/_config.yaml`` → ``agentic.patterns.*``
# and ``agentic.code_keywords``. The defaults are kept as a safety net
# so the module is still importable when the split layout is absent.
_BASELINE_RE = re.compile(r"\bP\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?\b", re.IGNORECASE)

# Bare program name (no baseline prefix), e.g. "HPPL486P", "J3021493".
# Used together with `_CODE_KEYWORDS_RE` to detect questions that need
# the full COBOL/target-language source context (loaded by ChatAgent via
# ContextBuilderService) rather than the lightweight workflow LLM path.
_PROGRAM_RE = re.compile(r"\b([A-Z]{1,6}\d{2,8}[A-Z]?)\b", re.IGNORECASE)

# Domain / code keywords that mean the user is asking about source code
# (mismatches, fixes, COBOL↔target comparison, snippet review). When any
# of these appear we MUST go through ChatAgent so the real files + strict
# `chat_skill.md` + `COBOL_TO_<LANG>_SKILL.MD` rules are applied. Without
# them the workflow LLM hallucinates "mismatches" from chat history alone.
_CODE_KEYWORDS_RE = re.compile(
    r"\b("
    r"cobol|csharp|c#|\.cs\b|\.cbl\b|"
    r"mismatch|mismatching|mis\s*match|"
    r"compare|comparison|diff|difference|"
    r"fix|bug|wrong|issue|error|"
    r"field|mapping|move\s+to|paragraph|"
    r"working[-\s]storage|pic\s+[9x]|"
    r"snippet|code"
    r")\b",
    re.IGNORECASE,
)


def _reconfigure_nl_patterns(
    baseline: Optional[str] = None,
    program: Optional[str] = None,
    code_keywords: Optional[List[str]] = None,
) -> None:
    """Rebuild the module-level NL detection regexes from config.

    Called by :class:`Orchestrator` at startup once the YAML config
    has been parsed. Any argument left as ``None`` keeps the current
    compiled pattern unchanged. Invalid regex input is logged and the
    existing default is preserved so dispatch never breaks.
    """
    global _BASELINE_RE, _PROGRAM_RE, _CODE_KEYWORDS_RE
    if baseline:
        try:
            _BASELINE_RE = re.compile(baseline, re.IGNORECASE)
        except re.error as exc:
            logger.warning(f"Invalid baseline regex in config ({exc}); keeping default")
    if program:
        try:
            _PROGRAM_RE = re.compile(program, re.IGNORECASE)
        except re.error as exc:
            logger.warning(f"Invalid program regex in config ({exc}); keeping default")
    if code_keywords:
        try:
            combined = r"\b(" + "|".join(code_keywords) + r")\b"
            _CODE_KEYWORDS_RE = re.compile(combined, re.IGNORECASE)
        except re.error as exc:
            logger.warning(
                f"Invalid code_keywords regex in config ({exc}); keeping default"
            )


def _looks_like_code_question(text: str) -> bool:
    """Return True if the user message needs full COBOL/target-language
    source context to answer correctly.

    The workflow LLM (``chat_with_tools`` in :meth:`agentic_dispatch`) is
    given only the workflow orchestration skill and the conversation
    history — it has NO COBOL or target source loaded. For domain
    questions it would otherwise hallucinate "mismatches" by replaying
    snippets from history. When this helper returns True, we delegate to
    the registered ``chat`` handler (``ChatAgent.chat_stream``) which
    loads the real files via :class:`ContextBuilderService` and applies
    the strict ``chat_skill.md`` + ``COBOL_TO_<LANG>_SKILL.MD`` rules.

    Triggers:
    * A baseline or bare program name (e.g. ``P02070-HPPL486P``, ``HPPL486P``)
    * Any domain / code keyword (compare, mismatch, fix, cobol, csharp, …)
    * A fenced code block in the message (user pasted a snippet)
    """
    if not text:
        return False
    if "```" in text:
        return True
    if _BASELINE_RE.search(text) or _PROGRAM_RE.search(text):
        return True
    if _CODE_KEYWORDS_RE.search(text):
        return True
    return False


def _stream_chunks(text: str, chunk_size: int = 24):
    """Yield ``text`` in small fixed-size chunks for streaming replay.

    Used by the agentic-dispatch text branch where the full response is
    already buffered (tool-calling requires buffering to detect tool
    calls). Chunking keeps the on-screen UX consistent with the true
    streaming path in :class:`agents.chat_agent.ChatAgent.chat_stream`.
    """
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


# ---------------------------------------------------------------------------
# Skill data model
# ---------------------------------------------------------------------------


@dataclass
class ArgSpec:
    name: str
    required: bool = False
    validation: Optional[str] = None
    usage: Optional[str] = None


@dataclass
class Operation:
    id: str
    command: str
    handler: str
    description: str = ""
    aliases: List[str] = field(default_factory=list)
    args: List[ArgSpec] = field(default_factory=list)
    intent_patterns: List[str] = field(default_factory=list)
    is_fallback: bool = False


# ---------------------------------------------------------------------------
# Skill loader
# ---------------------------------------------------------------------------


_YAML_BLOCK_RE = re.compile(
    r"```yaml\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

# Front-matter fence for per-operation skill files in the split layout.
# Each file starts with `---\n<yaml>\n---\n<markdown body>`.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z",
    re.DOTALL,
)


def _parse_frontmatter(text: str) -> tuple:
    """Split a `---`-fenced YAML front-matter file into (meta, body).

    Returns ``({}, text)`` if no front-matter fence is found so the
    caller can decide how to handle a malformed skill file.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    body = match.group(2)
    return (meta if isinstance(meta, dict) else {}), body


def _load_split_skill_layout(prompts_dir: Path) -> Optional[tuple]:
    """Load the new per-operation skill layout.

    Layout (see ``prompts/skills/``)::

        prompts/skills/
          orchestration/
            _messages.yaml      # UI message templates
            _powershell.yaml    # PowerShell cmdlet catalog
            _config.yaml        # ui.welcome_file + agentic.*
            _router.md          # Shared routing rules (LLM-readable)
          process/
            steps/      *_skill.md      # Per-step operations (copy, load, …)
            workflows/  *_skill.md      # Composite workflows (validate, reporting)
            meta/       *_skill.md      # Utilities + chat fallback

    Returns the same tuple shape as :func:`_load_skill_file` so the
    Orchestrator can use either loader interchangeably. Returns ``None``
    when the split layout is not present so the caller can fall back to
    the monolithic skill file (instant rollback path).
    """
    base = prompts_dir / "skills"
    orch_dir = base / "orchestration"
    proc_dir = base / "process"
    if not orch_dir.is_dir() or not proc_dir.is_dir():
        return None

    # ── 1. Shared YAML config ─────────────────────────────────────────
    def _read_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning(f"Malformed YAML in {path}: {exc}")
            return {}

    messages_doc = _read_yaml(orch_dir / "_messages.yaml")
    powershell_doc = _read_yaml(orch_dir / "_powershell.yaml")
    config_doc = _read_yaml(orch_dir / "_config.yaml")

    messages: Dict[str, Any] = messages_doc.get("messages") or {}
    ui: Dict[str, Any] = config_doc.get("ui") or {}
    agentic: Dict[str, Any] = config_doc.get("agentic") or {}

    ps_commands: Dict[str, Dict[str, Any]] = {}
    for entry in powershell_doc.get("powershell_commands") or []:
        if not isinstance(entry, dict):
            continue
        cmd_id = entry.get("id")
        if not cmd_id:
            logger.warning(f"Skipping powershell_commands entry without id: {entry!r}")
            continue
        ps_commands[str(cmd_id)] = {
            "id": str(cmd_id),
            "cmdlet": str(entry.get("cmdlet", "")),
            "args_template": str(entry.get("args_template", "")),
            "step": str(entry.get("step", "")),
            "purpose": str(entry.get("purpose", "")),
        }

    # ── 2. Per-operation skill files ──────────────────────────────────
    operations: Dict[str, Operation] = {}
    seen_ids: Dict[str, Path] = {}
    skill_bodies: Dict[str, str] = {}
    op_files = sorted(proc_dir.rglob("*_skill.md"))
    if not op_files:
        logger.warning(
            f"Split skill layout exists at {base} but no *_skill.md files "
            f"found under {proc_dir}. Falling back to monolithic skill."
        )
        return None

    for md_file in op_files:
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(f"Could not read skill file {md_file}: {exc}")
            continue

        meta, body = _parse_frontmatter(text)
        if not meta or "id" not in meta:
            logger.error(
                f"Skill file {md_file} missing YAML front-matter or 'id'. Skipping."
            )
            continue

        op_id = str(meta["id"])
        if op_id in seen_ids:
            # Loud failure: duplicate IDs are a configuration bug.
            raise ValueError(
                f"Duplicate operation id '{op_id}' in {md_file} "
                f"(already defined in {seen_ids[op_id]})"
            )
        seen_ids[op_id] = md_file

        try:
            op = _build_operation(meta)
        except Exception as exc:  # noqa: BLE001 — keep the loader resilient
            logger.error(f"Skipping invalid skill file {md_file} ({exc})")
            continue

        key = (op.command or op.id).lower()
        operations[key] = op
        for alias in op.aliases:
            if alias:
                operations[alias.lower()] = op

        # Cache the markdown body for the router-worker dispatch path.
        # Worker stage sends ONLY this string (+ shared routing rules)
        # instead of the concatenated 49 KB system prompt.
        skill_bodies[op_id] = body or ""

    if not operations:
        logger.warning(
            f"Split layout produced no operations from {proc_dir}. "
            "Falling back to monolithic skill."
        )
        return None

    # Tuck the skill bodies into agentic so the Orchestrator can pick
    # them up without changing the loader's return tuple shape.
    agentic["_skill_bodies"] = skill_bodies

    logger.info(
        f"Loaded {len(seen_ids)} operations and {len(ps_commands)} "
        f"powershell commands from split layout at {base} "
        f"({len(operations)} keyword bindings)"
    )
    return operations, ps_commands, messages, ui, agentic


def _load_skill_file(path: Path) -> tuple:
    """Parse the skill markdown and return ``(operations, ps_commands, messages, ui)``.

    The skill file may contain multiple YAML blocks; only the first one
    that defines ``operations`` is consumed.  ``powershell_commands``,
    ``messages`` and ``ui`` (if present in the same block) are parsed
    alongside so project-specific cmdlets, user-facing strings and UI
    asset paths stay co-located with their workflow operations.
    """
    if not path.exists():
        raise FileNotFoundError(f"Workflow skill file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    operations: Dict[str, Operation] = {}
    ps_commands: Dict[str, Dict[str, Any]] = {}
    messages: Dict[str, Any] = {}
    ui: Dict[str, Any] = {}
    agentic: Dict[str, Any] = {}

    for match in _YAML_BLOCK_RE.finditer(raw):
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            logger.warning(f"Skipping malformed YAML block in {path.name}: {exc}")
            continue

        ops = data.get("operations") if isinstance(data, dict) else None
        if not ops:
            continue

        for entry in ops:
            try:
                op = _build_operation(entry)
            except Exception as exc:  # noqa: BLE001 — keep the loader resilient
                logger.error(f"Skipping invalid operation entry: {entry!r} ({exc})")
                continue

            key = (op.command or op.id).lower()
            operations[key] = op
            for alias in op.aliases:
                if alias:
                    operations[alias.lower()] = op

        # Parse PowerShell command catalog from the same block (optional).
        for entry in data.get("powershell_commands") or []:
            if not isinstance(entry, dict):
                continue
            cmd_id = entry.get("id")
            if not cmd_id:
                logger.warning(f"Skipping powershell_commands entry without id: {entry!r}")
                continue
            ps_commands[str(cmd_id)] = {
                "id": str(cmd_id),
                "cmdlet": str(entry.get("cmdlet", "")),
                "args_template": str(entry.get("args_template", "")),
                "step": str(entry.get("step", "")),
                "purpose": str(entry.get("purpose", "")),
            }

        # Parse user-facing message templates from the same block (optional).
        msg_block = data.get("messages")
        if isinstance(msg_block, dict):
            messages = msg_block

        # Parse UI asset paths (welcome page, help file, etc.) (optional).
        ui_block = data.get("ui")
        if isinstance(ui_block, dict):
            ui = ui_block

        # Parse agentic orchestration config (optional).
        agentic_block = data.get("agentic")
        if isinstance(agentic_block, dict):
            agentic = agentic_block

        break  # only consume the first ``operations:`` block

    if not operations:
        raise ValueError(
            f"No operations parsed from skill file: {path}. "
            "Check the YAML block and 'operations:' key."
        )

    logger.info(
        f"Loaded {len({op.id for op in operations.values()})} operations "
        f"and {len(ps_commands)} powershell commands "
        f"from {path.name} ({len(operations)} keyword bindings)"
    )
    return operations, ps_commands, messages, ui, agentic


def _build_operation(entry: Dict[str, Any]) -> Operation:
    arg_specs: List[ArgSpec] = []
    for arg in entry.get("args") or []:
        if not isinstance(arg, dict):
            continue
        arg_specs.append(
            ArgSpec(
                name=arg.get("name", ""),
                required=bool(arg.get("required", False)),
                validation=arg.get("validation"),
                usage=arg.get("usage"),
            )
        )

    return Operation(
        id=entry["id"],
        command=str(entry.get("command", entry["id"])),
        handler=str(entry.get("handler", entry["id"])),
        description=str(entry.get("description", "")),
        aliases=list(entry.get("aliases") or []),
        args=arg_specs,
        intent_patterns=list(entry.get("intent_patterns") or []),
        is_fallback=bool(entry.get("is_fallback", False)),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Skill-driven message dispatcher.

    The orchestrator is intentionally tiny and mechanical: it looks up a
    handler in the registry and calls it.  All UX (messages, heartbeats,
    action buttons) lives inside the handlers themselves.
    """

    DEFAULT_SKILL_PATH = (
        Path(config.BASE_DIR) / "prompts" / "WORKFLOW_ORCHESTRATION_SKILL.md"
    )

    def __init__(self, skill_path: Optional[Path] = None) -> None:
        self._skill_path = Path(skill_path) if skill_path else self.DEFAULT_SKILL_PATH

        # Prefer the new split layout (prompts/skills/) — easier to
        # maintain, one file per operation. Fall back to the monolithic
        # WORKFLOW_ORCHESTRATION_SKILL.md if the split layout is absent
        # so deleting `prompts/skills/` is a one-step rollback.
        prompts_dir = Path(config.BASE_DIR) / "prompts"
        split_loaded = _load_split_skill_layout(prompts_dir)
        if split_loaded is not None:
            (
                self._operations,
                self._ps_commands,
                self._messages,
                self._ui,
                self._agentic,
            ) = split_loaded
            self._using_split_layout = True
        else:
            (
                self._operations,
                self._ps_commands,
                self._messages,
                self._ui,
                self._agentic,
            ) = _load_skill_file(self._skill_path)
            self._using_split_layout = False
        self._registry = get_tool_registry()
        self._fallback_op: Optional[Operation] = next(
            (op for op in self._operations.values() if op.is_fallback),
            None,
        )
        # Eagerly load the welcome markdown (one-time disk read) so the
        # on_chat_start handler is a pure in-memory lookup.
        self._welcome_text: Optional[str] = self._load_welcome_text()

        # Agentic dispatch: cache skill-file raw text and tool schemas once.
        self._skill_system_prompt: Optional[str] = None
        self._tool_schemas: Optional[List[Dict[str, Any]]] = None

        # Handler name → Operation lookup for agentic dispatch (tool names
        # match handler names, but operations are keyed by command).
        self._handler_ops: Dict[str, Operation] = {
            op.handler: op
            for op in self._operations.values()
            if op.handler
        }

        # ── Router-worker (Stage-1 + Stage-2) caches ─────────────────
        # Per-operation markdown body (LLM-readable description loaded
        # ONLY when that skill is selected). Populated by the split
        # loader; empty dict for the monolithic fallback so router-worker
        # auto-degrades to the legacy path.
        self._skill_bodies: Dict[str, str] = self._agentic.pop(
            "_skill_bodies", {}
        ) if isinstance(self._agentic, dict) else {}
        # id → Operation lookup for router-worker (canonical id, not command).
        self._id_to_op: Dict[str, Operation] = {}
        for op in self._operations.values():
            if op.id not in self._id_to_op:
                self._id_to_op[op.id] = op
        # Cached lazily on first use.
        self._router_system_prompt: Optional[str] = None
        # Cached single-tool schemas keyed by operation id (built once,
        # reused across messages — no per-message allocation cost).
        self._single_tool_schemas: Dict[str, List[Dict[str, Any]]] = {}

        # ── Config-driven extraction overrides (safe defaults baked in)
        # Reconfigure module-level NL regexes from config so the
        # baseline/program/code-keyword patterns can be tuned per
        # client without touching Python. Values are validated in
        # ``_reconfigure_nl_patterns`` — invalid regex falls back to
        # the built-in default.
        patterns_cfg = (
            self._agentic.get("patterns") if isinstance(self._agentic, dict) else None
        ) or {}
        code_kw_cfg = (
            self._agentic.get("code_keywords") if isinstance(self._agentic, dict) else None
        )
        _reconfigure_nl_patterns(
            baseline=patterns_cfg.get("baseline"),
            program=patterns_cfg.get("program"),
            code_keywords=code_kw_cfg if isinstance(code_kw_cfg, list) else None,
        )

        # Stream chunk size for buffered LLM text replay. Read once,
        # cached, falls back to historical default 24 chars.
        ui_cfg = self._ui if isinstance(self._ui, dict) else {}
        try:
            self._stream_chunk_size: int = int(ui_cfg.get("stream_chunk_size", 24)) or 24
        except (TypeError, ValueError):
            self._stream_chunk_size = 24

        # Lazily-loaded router/worker instruction text (paths from
        # _config.yaml). Empty string means "use built-in default".
        self._router_instruction_text: Optional[str] = None
        self._worker_instruction_text: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def known_commands(self) -> List[str]:
        """Return all command keywords (excluding the fallback)."""
        return sorted(
            {
                op.command.lower()
                for op in self._operations.values()
                if not op.is_fallback and op.command
            }
        )

    def get_powershell_command(self, cmd_id: str) -> Dict[str, Any]:
        """Return the skill-defined PowerShell command spec by id.

        Raises ``KeyError`` if the id is not declared in the skill file —
        this is intentional: missing PS commands are a configuration bug,
        not a runtime fallback case.
        """
        try:
            return self._ps_commands[cmd_id]
        except KeyError:
            raise KeyError(
                f"PowerShell command '{cmd_id}' is not defined in the skill "
                f"file ({self._skill_path.name}). Known: "
                f"{sorted(self._ps_commands)}"
            )

    def get_message(self, key: str, **kwargs: Any) -> str:
        """Return a user-facing message template from the skill file.

        ``key`` is a dot-path into the ``messages:`` block, e.g.
        ``"usage.copy"`` resolves to ``messages.usage.copy``.

        Any ``**kwargs`` are applied via :py:meth:`str.format` so templates
        can use ``{baseline}``, ``{error}``, etc.  A missing key returns a
        clearly-tagged sentinel so the chat still works but the bug is
        visible to maintainers (mirrors today's behaviour where a wrong
        string would simply render as-is).
        """
        node: Any = self._messages
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                logger.warning(f"Skill message key not found: '{key}'")
                return f"<missing skill message: {key}>"
            node = node[part]

        if not isinstance(node, str):
            logger.warning(f"Skill message key '{key}' is not a string")
            return f"<invalid skill message: {key}>"

        if not kwargs:
            return node
        try:
            return node.format(**kwargs)
        except (KeyError, IndexError) as exc:
            logger.warning(f"Skill message '{key}' format error: {exc}")
            return node

    def get_welcome_text(self) -> Optional[str]:
        """Return the cached welcome markdown, or ``None`` if not configured.

        The text is read once at startup from the path declared at
        ``ui.welcome_file`` in the skill file.  Callers should fall back
        to a hard-coded default when this returns ``None`` so the chat
        never breaks if the file is missing.
        """
        return self._welcome_text

    def _load_welcome_text(self) -> Optional[str]:
        """One-shot loader for the welcome markdown referenced by the skill."""
        rel = self._ui.get("welcome_file") if isinstance(self._ui, dict) else None
        if not rel or not isinstance(rel, str):
            return None

        # Resolve relative to the project root (BASE_DIR) for consistency
        # with the skill-file path itself.
        path = (Path(config.BASE_DIR) / rel).resolve()
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Welcome file '{path}' could not be read: {exc}")
            return None

    async def dispatch(self, content: str) -> None:
        """Route a user message to the appropriate handler.

        ``content`` is the raw text from the user.  This method never raises
        — unexpected errors are logged and surfaced via the chat fallback
        so the chat loop stays alive.
        """
        text = (content or "").strip()
        if not text:
            await self._dispatch_fallback(text)
            return

        parts = text.split(maxsplit=1)
        keyword = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        op = self._operations.get(keyword)

        # Tier-1 fast path: command keyword in the leading position.
        if op is not None and not op.is_fallback:
            await self._invoke_operation(op, args, source="command")
            return

        # Tier-2 NL intent detection: scan the whole sentence for an
        # operation keyword + a baseline name.  This lets free-form
        # requests like "please copy the baseline P02070-HPPL486P" or
        # "run validation on P02070-HPPL494P" actually execute, instead
        # of falling through to the chat fallback (which only talks).
        nl_match = self._match_nl_intent(text)
        if nl_match is not None:
            nl_op, nl_args = nl_match
            await self._invoke_operation(nl_op, nl_args, source="nl")
            return

        # Tier-3 fallback: free-form chat / Q&A.
        logger.info(f"Orchestrator: '{keyword}' → fallback (chat)")
        await self._dispatch_fallback(text)

    # ------------------------------------------------------------------
    # Agentic dispatch (LLM-driven)
    # ------------------------------------------------------------------
    # All configuration is read from the skill file's ``agentic:`` block.
    # Zero hardcoded values in Python.

    def _get_skill_system_prompt(self) -> str:
        """Load and cache all skill markdown files as the LLM system
        prompt, prefixed with orchestrator instructions from the skill
        file's ``agentic.system_prompt``.

        When the split layout (``prompts/skills/``) is active, this
        includes ``orchestration/_router.md`` + every
        ``process/**/*_skill.md`` plus the surviving root-level skills
        (``chat_skill.md``, ``REPORTING_SKILL.md``,
        ``COBOL_TO_<LANG>_SKILL.MD``). The monolithic
        ``WORKFLOW_ORCHESTRATION_SKILL.md`` is skipped to avoid duplicate
        content.

        Read once, cached for process lifetime.
        """
        if self._skill_system_prompt is not None:
            return self._skill_system_prompt

        # Orchestrator instructions from skill file (not hardcoded).
        instructions = self._agentic.get("system_prompt", "")

        prompts_dir = Path(config.BASE_DIR) / "prompts"
        parts: List[str] = []
        seen: set = set()

        def _append(md_file: Path) -> None:
            try:
                resolved = md_file.resolve()
            except OSError:
                resolved = md_file
            if resolved in seen:
                return
            seen.add(resolved)
            try:
                parts.append(
                    f"# ── {md_file.name} ──\n\n"
                    + md_file.read_text(encoding="utf-8")
                )
            except OSError as exc:
                logger.warning(f"Could not read skill file {md_file}: {exc}")

        # Root-level *.md skills (chat_skill, REPORTING_SKILL,
        # COBOL_TO_<LANG>_SKILL, etc.) — same as before. When the split
        # layout is active, the monolithic workflow skill is skipped
        # because its content now lives under prompts/skills/.
        for md_file in sorted(prompts_dir.glob("*.md")):
            stem_lower = md_file.stem.lower()
            if stem_lower == "welcome":
                continue
            if (
                self._using_split_layout
                and md_file.name == self._skill_path.name
            ):
                continue
            _append(md_file)

        # Split layout: router rules + every per-operation skill body.
        if self._using_split_layout:
            split_root = prompts_dir / "skills"
            router_md = split_root / "orchestration" / "_router.md"
            if router_md.exists():
                _append(router_md)
            for md_file in sorted((split_root / "process").rglob("*_skill.md")):
                _append(md_file)

        skill_text = "\n\n".join(parts) if parts else ""
        self._skill_system_prompt = instructions + "\n\n" + skill_text
        logger.info(
            f"Agentic system prompt built from {len(parts)} skill files "
            f"({len(self._skill_system_prompt)} chars)"
        )
        return self._skill_system_prompt

    def _get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Build and cache OpenAI function-calling tool schemas from the
        handler registry + skill-file operation descriptions.

        Uses ``agentic.excluded_tools`` and ``agentic.tool_schema`` from
        the skill file for configuration."""
        if self._tool_schemas is not None:
            return self._tool_schemas

        excluded = self._agentic.get("excluded_tools", ["chat"])
        schema_cfg = self._agentic.get("tool_schema", {})
        arg_param = schema_cfg.get("arg_parameter_name", "args")
        arg_desc_fallback = schema_cfg.get(
            "arg_description_fallback", "Argument for {name}"
        )

        # Build a lookup: handler_name → operation (for descriptions).
        # Fallback ops are included so `excluded_tools` is the sole
        # mechanism for hiding tools from the LLM.
        handler_ops: Dict[str, Operation] = {}
        for op in self._operations.values():
            if op.handler and op.handler not in handler_ops:
                handler_ops[op.handler] = op

        schemas: List[Dict[str, Any]] = []
        for name in self._registry.names():
            if name in excluded:
                continue

            op = handler_ops.get(name)
            description = (op.description if op else "") or f"Execute the '{name}' operation."

            # If the operation has args, expose a string parameter.
            has_args = bool(op and op.args)
            if has_args:
                arg_desc = op.args[0].usage or arg_desc_fallback.format(name=name)
                parameters: Dict[str, Any] = {
                    "type": "object",
                    "properties": {
                        arg_param: {
                            "type": "string",
                            "description": arg_desc,
                        }
                    },
                    "required": [arg_param],
                }
            else:
                parameters = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }

            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            })

        self._tool_schemas = schemas
        logger.info(f"Built {len(schemas)} tool schemas for agentic dispatch")
        return self._tool_schemas

    async def agentic_dispatch(
        self,
        content: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """LLM-driven dispatch with selectable routing strategy.

        Two modes (configured in ``prompts/skills/orchestration/_config.yaml``
        as ``agentic.routing_mode``):

        * ``router_worker`` (default) — Stage-1 router picks one skill;
          Stage-2 worker LLM call loads ONLY that skill body + that
          single tool schema. ~60-70 % smaller LLM prompt per message.
        * ``legacy`` — original behaviour: every message gets ALL skill
          files + ALL tool schemas. Use this to A/B or to roll back
          instantly if the new router misroutes anything.

        The router-worker path automatically degrades to legacy when:
          * The split skill layout is not active (no per-op bodies cached).
          * The LLM service is unavailable for the router call.
        """
        text = (content or "").strip()
        if not text:
            await self._dispatch_fallback(text)
            return {"role": "assistant", "tool": None, "args": "", "baseline": None}

        mode = str(self._agentic.get("routing_mode", "router_worker")).lower()
        if (
            mode != "legacy"
            and self._using_split_layout
            and self._skill_bodies
        ):
            return await self._router_worker_dispatch(text, conversation_history)
        return await self._legacy_agentic_dispatch(text, conversation_history)

    async def _legacy_agentic_dispatch(
        self,
        content: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Original monolithic-prompt dispatch (kept verbatim).

        Sends ALL skill files + ALL tools every message. Used as the
        rollback path and when the split layout is unavailable.

        Parameters
        ----------
        content:
            Raw user message text.
        conversation_history:
            Optional list of prior turns (``{"role": ..., "content": ...}``)
            so the LLM can resolve references like "it", "that baseline",
            "now load", etc.  Managed by the caller (``app.py``) via
            Chainlit's ``cl.user_session``.

        Returns
        -------
        dict with ``{"role": "assistant", "tool": <name|None>,
        "args": <str>, "baseline": <str|None>}`` — a compact summary
        the caller appends to its conversation history store.
        """
        text = (content or "").strip()
        if not text:
            await self._dispatch_fallback(text)
            return {"role": "assistant", "tool": None, "args": "", "baseline": None}

        # ── LLM-driven tool selection ────────────────────────────────
        try:
            from services.llm_service import get_llm_service
            llm = get_llm_service()
        except Exception as exc:
            logger.warning(f"LLM service unavailable, falling back to keyword dispatch: {exc}")
            await self.dispatch(text)
            return {"role": "assistant", "tool": "_keyword_fallback", "args": text, "baseline": None}

        system_prompt = self._get_skill_system_prompt()
        tool_schemas = self._get_tool_schemas()

        # Build message list: system → conversation history → current user.
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Inject recent conversation history so the LLM can resolve
        # pronouns and short references ("it", "that baseline", "now load").
        max_history = int(self._agentic.get("max_history_turns", 10))
        if conversation_history:
            for turn in conversation_history[-max_history:]:
                role = turn.get("role", "user")
                body = turn.get("content", "")
                if role in ("user", "assistant") and body:
                    messages.append({"role": role, "content": body})

        messages.append({"role": "user", "content": text})

        max_iters = int(self._agentic.get("max_iterations", 10))
        for iteration in range(max_iters):
            try:
                assistant_msg = await llm.chat_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                )
            except Exception as exc:
                logger.warning(
                    f"LLM tool-call failed (iteration {iteration}), "
                    f"falling back to keyword dispatch: {exc}"
                )
                await self.dispatch(text)
                return {"role": "assistant", "tool": "_keyword_fallback", "args": text, "baseline": None}

            tool_calls = assistant_msg.get("tool_calls")

            # No tool call → LLM decided this is a conversational message.
            #
            # Two sub-paths:
            #
            # (a) **Domain / code question** (program name, "compare",
            #     "mismatch", "fix", pasted snippet, etc.) → delegate to
            #     the registered ``chat`` handler. That handler runs
            #     ``ChatAgent.chat_stream``, which loads the real COBOL
            #     and target-language files via ContextBuilderService and
            #     applies the strict ``chat_skill.md`` +
            #     ``COBOL_TO_<LANG>_SKILL.MD`` rules ("snippet is broken,
            #     real file is truth, no extras, no fabrication"). This
            #     is the ONLY path with real source code in the prompt
            #     — without it the workflow LLM hallucinates mismatches
            #     by replaying snippets from ``agentic_history``.
            #
            # (b) **Workflow follow-up / chit-chat** ("give me a
            #     summary", "what was the result?", "thanks") → use the
            #     LLM's own text response. It has the workflow
            #     ``agentic_history`` (with rich handler output) which
            #     is exactly what those follow-ups need; running it
            #     through ChatAgent would lose that history.
            #
            # If the LLM returned no useful text (empty response) we
            # also delegate to the chat handler as a safety net.
            if not tool_calls:
                llm_text = (assistant_msg.get("content") or "").strip()
                if _looks_like_code_question(text):
                    logger.info(
                        "Agentic dispatch: no tool call, code/domain question "
                        "→ delegating to chat handler (real source context)"
                    )
                    await self._dispatch_fallback(text)
                elif llm_text:
                    logger.info("Agentic dispatch: no tool call → LLM text response")
                    import chainlit as cl
                    # Stream the response token-by-token (ChatGPT/Copilot
                    # style). The text is already fully received from
                    # chat_with_tools (which must buffer to detect
                    # tool_calls), so we replay it in word chunks for a
                    # consistent streaming UX without any extra LLM call.
                    msg = cl.Message(content="")
                    await msg.send()
                    try:
                        for chunk in _stream_chunks(llm_text, self._stream_chunk_size):
                            await msg.stream_token(chunk)
                    except Exception as stream_exc:
                        logger.warning(
                            f"Agentic stream replay failed, "
                            f"falling back to single send: {stream_exc}"
                        )
                        msg.content = llm_text
                    else:
                        # Final trim guard — ensures the sealed message is
                        # the canonical, whitespace-trimmed response.
                        msg.content = llm_text
                    await msg.update()
                else:
                    logger.info("Agentic dispatch: no tool call, no text → chat fallback")
                    await self._dispatch_fallback(text)
                return {"role": "assistant", "tool": None, "args": "", "baseline": None}

            # Append assistant message (with tool_calls) to conversation.
            messages.append(assistant_msg)

            # Process each tool call.
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                tc_id = tc.get("id", "")

                # Whitelist: only registered handlers can be called.
                handler = self._registry.get(tool_name)
                if handler is None:
                    logger.warning(
                        f"Agentic dispatch: LLM called unknown tool '{tool_name}'. Ignoring."
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Error: unknown tool '{tool_name}'.",
                    })
                    continue

                # Parse arguments.
                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    parsed = {}
                schema_cfg = self._agentic.get("tool_schema", {})
                arg_param = schema_cfg.get("arg_parameter_name", "args")
                args_str = parsed.get(arg_param, "")

                logger.info(
                    f"Agentic dispatch [{iteration}]: tool='{tool_name}' "
                    f"args='{args_str}'"
                )

                # Execute handler — same call path as keyword dispatch.
                # Look up by command first, then by handler name (tools
                # are named after handlers, but operations are keyed by
                # command which may differ, e.g. __fallback__ vs chat).
                try:
                    op = self._operations.get(tool_name) or self._handler_ops.get(tool_name)
                    if op and op.args:
                        await handler(args_str)
                    else:
                        await handler()
                    tool_result = f"Tool '{tool_name}' executed successfully."
                except Exception as exc:
                    logger.exception(f"Agentic handler '{tool_name}' raised: {exc}")
                    tool_result = f"Tool '{tool_name}' failed: {exc}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result,
                })

            # After all tool calls in this iteration are processed, the
            # handler already sent its own Chainlit messages (same as
            # keyword dispatch).  We do NOT loop back to the LLM for a
            # "summary" — the handler output IS the user-facing response.
            # This preserves identical UX to the keyword path.
            #
            # Return a summary so the caller can store it in conversation
            # history.  Extract baseline from args for context tracking.
            first_tc = tool_calls[0].get("function", {})
            called_tool = first_tc.get("name", "")
            called_args = args_str  # from last parsed tool call
            detected_baseline = self._extract_baseline(called_args) or self._extract_baseline(text)
            return {
                "role": "assistant",
                "tool": called_tool,
                "args": called_args,
                "baseline": detected_baseline,
            }

    # ------------------------------------------------------------------
    # Router-Worker dispatch (orchestrator-worker pattern)
    # ------------------------------------------------------------------
    # Two-stage LLM dispatch that loads ONLY the skill file relevant to
    # the current user request, instead of concatenating all 15 skills
    # on every message.
    #
    # Stage 1 — Router
    #   (a) Deterministic keyword router (free, instant). Matches the
    #       first token of the message against every operation's
    #       ``command`` and ``aliases``.
    #   (b) LLM router fallback (tiny prompt: op-id + 1-line each).
    #       Used only when the keyword router misses. Returns an
    #       operation id (or ``chat`` for free-form Q&A).
    #
    # Stage 2 — Worker
    #   Calls ``chat_with_tools`` with system_prompt = shared routing
    #   rules + the single chosen skill body, tools = [single tool].
    #   The handler-execution loop is identical to the legacy path so
    #   UX (Chainlit messages, action buttons, session state) does not
    #   change.

    def _read_instruction_file(self, rel_path: str) -> str:
        """Read an instruction markdown file relative to ``prompts/``.

        Strips the leading HTML comment block (``<!-- ... -->``) used
        for maintainer notes so it never reaches the LLM. Raises if
        the path is empty, missing, or unreadable — a missing skill
        file is a deployment bug that must fail loudly at startup.
        """
        if not rel_path:
            raise ValueError(
                "Instruction file path is empty in agentic config. "
                "Set 'router_instruction_file' / 'worker_instruction_file' "
                "in prompts/skills/orchestration/_config.yaml."
            )
        path = Path(config.BASE_DIR) / "prompts" / rel_path
        raw = path.read_text(encoding="utf-8")
        # Drop leading HTML comment block (single, at top of file).
        stripped = re.sub(r"^\s*<!--.*?-->\s*", "", raw, count=1, flags=re.DOTALL)
        return stripped.strip()

    def _load_router_instruction(self) -> str:
        """Return cached router-instruction text (loaded from config)."""
        if self._router_instruction_text is None:
            rel = self._agentic.get("router_instruction_file", "")
            self._router_instruction_text = self._read_instruction_file(rel)
        return self._router_instruction_text

    def _load_worker_instruction(self, op_id: str, handler: str) -> str:
        """Return worker-instruction text with placeholders substituted."""
        if self._worker_instruction_text is None:
            rel = self._agentic.get("worker_instruction_file", "")
            self._worker_instruction_text = self._read_instruction_file(rel)
        return self._worker_instruction_text.format(op_id=op_id, handler=handler)

    def _get_router_system_prompt(self) -> str:
        """Build (and cache) the tiny router prompt.

        Contents:
          1. Shared routing rules from ``orchestration/_router.md``.
          2. ``agentic.system_prompt`` (pronoun rules, decide-which-tool
             rules) so the router has the same memory hints as legacy.
          3. A one-line summary per operation: ``- <id>: <description>``.
          4. JSON-mode instruction: response MUST be a single JSON
             object ``{"operation": "<id>", "args": "<extracted args>"}``.
        """
        if self._router_system_prompt is not None:
            return self._router_system_prompt

        prompts_dir = Path(config.BASE_DIR) / "prompts"
        router_md = prompts_dir / "skills" / "orchestration" / "_router.md"
        rules_text = ""
        if router_md.exists():
            try:
                rules_text = router_md.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(f"Could not read {router_md}: {exc}")

        instructions = self._agentic.get("system_prompt", "")
        # One-line operation catalog for the router. Ordering: leaf
        # steps first, then composites, then utilities, then chat.
        lines: List[str] = []
        for op in sorted(self._id_to_op.values(), key=lambda o: o.id):
            if op.is_fallback:
                continue
            lines.append(f"- {op.id}: {op.description}".rstrip())
        # Always advertise the chat fallback explicitly.
        chat_op = next(
            (o for o in self._id_to_op.values() if o.is_fallback), None
        )
        if chat_op is not None:
            lines.append(
                f"- chat: {chat_op.description.strip() or 'Free-form Q&A / knowledge base.'}"
            )
        catalog = "\n".join(lines)

        router_instruction_body = self._load_router_instruction()
        router_instruction = (
            f"{router_instruction_body}\n\n"
            "Available operations:\n"
            f"{catalog}\n"
        )

        parts = [router_instruction]
        if rules_text:
            parts.append(rules_text)
        if instructions:
            # Drop the legacy "skill files below" hint — there are none
            # at the router stage. Keep the memory / pronoun rules.
            parts.append(instructions)
        self._router_system_prompt = "\n\n".join(parts)
        logger.info(
            f"Router system prompt built ({len(self._router_system_prompt)} chars, "
            f"{len(self._id_to_op)} operations)"
        )
        return self._router_system_prompt

    def _get_single_tool_schema(self, op_id: str) -> List[Dict[str, Any]]:
        """Return a single-element tools list for the worker call.

        Built lazily and cached per operation id so repeated worker
        calls allocate nothing.
        """
        if op_id in self._single_tool_schemas:
            return self._single_tool_schemas[op_id]

        op = self._id_to_op.get(op_id)
        if op is None:
            # Defensive: caller already guards against unknown ids.
            return []

        excluded = self._agentic.get("excluded_tools", [])
        if op.handler in excluded:
            self._single_tool_schemas[op_id] = []
            return []

        schema_cfg = self._agentic.get("tool_schema", {})
        arg_param = schema_cfg.get("arg_parameter_name", "args")
        arg_desc_fallback = schema_cfg.get(
            "arg_description_fallback", "Argument for {name}"
        )
        description = op.description or f"Execute the '{op.handler}' operation."
        if op.args:
            arg_desc = op.args[0].usage or arg_desc_fallback.format(name=op.handler)
            parameters: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    arg_param: {"type": "string", "description": arg_desc}
                },
                "required": [arg_param],
            }
        else:
            parameters = {"type": "object", "properties": {}, "required": []}

        schema = [{
            "type": "function",
            "function": {
                "name": op.handler,
                "description": description,
                "parameters": parameters,
            },
        }]
        self._single_tool_schemas[op_id] = schema
        return schema

    def _deterministic_route(self, text: str) -> Optional[str]:
        """Free / instant Stage-1 router.

        Lowercase the first whitespace-separated token of the message
        and look it up in the keyword catalog (commands + aliases).
        Returns the matched operation's ``id`` (NOT command), or
        ``None`` when no exact keyword hit is found.

        The chat fallback is intentionally NOT returned here — that is
        the LLM router's decision (free-form messages should go through
        Stage-1b, not be auto-classified as chat).
        """
        if not text:
            return None
        first = text.split(maxsplit=1)[0].lower()
        op = self._operations.get(first)
        if op is None or op.is_fallback:
            return None
        return op.id

    async def _llm_route(
        self,
        text: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> List[Tuple[str, str]]:
        """Stage-1b: ask the LLM to pick one OR MORE operation ids.

        Uses the plain ``chat`` endpoint (no tools) with a tiny prompt
        and parses the JSON response. Returns a list of
        ``(op_id, args)`` pairs in execution order so the caller can
        run multi-step requests ("copy and load X") sequentially.
        Returns ``[("chat", text)]`` as the natural fallback when the
        router picks the chat handler.

        Accepted JSON shapes:
          * ``{"operation": "<id>", "args": "<args>"}``           single op
          * ``{"operations": [{"id":..., "args":...}, ...]}``    multi-op

        Conversation history is folded into the user prompt as a short
        transcript so pronouns like "it" / "that baseline" still work.
        Raises on transport failure so the caller can degrade to legacy.
        """
        try:
            from services.llm_service import get_llm_service
            llm = get_llm_service()
        except Exception as exc:
            logger.warning(f"Router LLM service unavailable: {exc}")
            raise

        system_prompt = self._get_router_system_prompt()

        # Fold last N turns into the user prompt. Keep it short to
        # protect the router's small token budget.
        max_history = int(self._agentic.get("max_history_turns", 10))
        history_lines: List[str] = []
        if conversation_history:
            for turn in conversation_history[-max_history:]:
                role = turn.get("role", "user")
                body = (turn.get("content") or "").strip()
                if not body or role not in ("user", "assistant"):
                    continue
                # Truncate long assistant outputs — the router only
                # needs the gist for pronoun resolution.
                if len(body) > 400:
                    body = body[:400] + "…"
                history_lines.append(f"{role}: {body}")
        history_block = "\n".join(history_lines)
        user_prompt = (
            (f"Recent conversation:\n{history_block}\n\n" if history_block else "")
            + f"Current user message:\n{text}\n\n"
            "Return the JSON object now."
        )

        try:
            raw = await llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=400,
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning(f"Router LLM call failed: {exc}")
            raise

        # The LLM may wrap the JSON in fences despite instructions; be
        # forgiving and extract the first balanced {...} block.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            logger.warning(f"Router returned non-JSON: {raw!r}")
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            logger.warning(f"Router JSON parse failed ({exc}): {raw!r}")
            return []

        plan: List[Tuple[str, str]] = []
        # Multi-op shape first — ordered list of {id, args}.
        ops_list = data.get("operations")
        if isinstance(ops_list, list) and ops_list:
            for entry in ops_list:
                if not isinstance(entry, dict):
                    continue
                op_id = str(entry.get("id") or entry.get("operation") or "").strip()
                if not op_id:
                    continue
                args = str(entry.get("args") or "").strip()
                plan.append((op_id, args))
        else:
            # Single-op shape — backwards-compatible.
            op_id = str(data.get("operation") or "").strip()
            if op_id:
                plan.append((op_id, str(data.get("args") or "").strip()))

        # Keep the legacy attribute populated with the FIRST op's args
        # so downstream worker code that consults `_last_router_args`
        # behaves identically for single-op requests.
        self._last_router_args = plan[0][1] if plan else ""
        return plan

    async def _router_worker_dispatch(
        self,
        text: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """Stage-1 + Stage-2 dispatch.

        Identical user-facing behaviour to the legacy path; the only
        difference is which (and how many) skill files are loaded into
        the worker prompt.

        Routing is fully LLM-driven so the model understands intent,
        synonyms and natural-language phrasing the same way the legacy
        path did. There is NO deterministic keyword shortcut — every
        message is classified by the router LLM.

        Multi-step requests ("copy and load X", "do step 1 and step 2")
        are supported: the router returns an ordered list of ops and
        the worker executes them one at a time, appending each result
        into the conversation history passed to the next worker call
        so it can resolve pronouns and reuse the baseline.
        """
        self._last_router_args = ""

        # Stage 1: LLM-based intent routing (no keyword shortcut).
        try:
            plan = await self._llm_route(text, conversation_history)
        except Exception as exc:
            logger.warning(
                f"Router-worker: LLM router unavailable ({exc}) "
                "→ falling back to legacy dispatch"
            )
            return await self._legacy_agentic_dispatch(text, conversation_history)
        route_source = "llm"

        # No plan / explicit chat → delegate to fallback handler.
        if not plan or (len(plan) == 1 and plan[0][0] == "chat"):
            chosen = plan[0][0] if plan else None
            logger.info(
                f"Router-worker [{route_source}]: routed to chat fallback "
                f"(op_id={chosen!r})"
            )
            await self._dispatch_fallback(text)
            return {"role": "assistant", "tool": None, "args": "", "baseline": None}

        # Validate every op id up-front; if any is unknown, degrade
        # cleanly to the legacy single-call path so the request still
        # produces some response instead of partial execution.
        ops_to_run: List[Tuple[Operation, str]] = []
        for op_id, args in plan:
            if op_id == "chat":
                # Don't mix chat into a workflow sequence — router was
                # told not to do this, but guard anyway.
                logger.warning(
                    f"Router-worker [{route_source}]: 'chat' embedded in "
                    f"multi-op plan {plan!r}; skipping it"
                )
                continue
            op = self._id_to_op.get(op_id)
            if op is None or op.is_fallback:
                logger.warning(
                    f"Router-worker [{route_source}]: unknown op id '{op_id}' "
                    f"in plan {plan!r} → falling back to legacy dispatch"
                )
                return await self._legacy_agentic_dispatch(text, conversation_history)
            ops_to_run.append((op, args))

        if not ops_to_run:
            await self._dispatch_fallback(text)
            return {"role": "assistant", "tool": None, "args": "", "baseline": None}

        logger.info(
            f"Router-worker [{route_source}]: plan={[(o.id, a) for o, a in ops_to_run]}"
        )

        # Execute each op sequentially. After every op, append a
        # synthetic assistant turn into the history we pass to the
        # next worker so it can resolve pronouns and reuse the
        # baseline (mirrors how on_message persists history between
        # user turns).
        running_history: List[Dict[str, str]] = list(conversation_history or [])
        last_result: Dict[str, Any] = {
            "role": "assistant", "tool": None, "args": "", "baseline": None,
        }
        for index, (op, args) in enumerate(ops_to_run):
            # Seed the per-op router-arg hint from the plan so the
            # worker LLM has the baseline even when the user's raw
            # message only mentioned it once at the start.
            self._last_router_args = args
            last_result = await self._llm_invoke_skill(
                op, text, running_history,
            )
            # Append this op's outcome so the next worker sees it.
            if index < len(ops_to_run) - 1 and last_result:
                running_history.append({"role": "user", "content": text})
                summary = (
                    f"Executed tool '{last_result.get('tool') or op.handler}' "
                    f"with args '{last_result.get('args') or args}'."
                )
                running_history.append({"role": "assistant", "content": summary})
        return last_result

    async def _llm_invoke_skill(
        self,
        op: Operation,
        text: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """Stage-2 worker: load ONLY this op's skill body + tool.

        The handler-execution loop is intentionally identical in shape
        to ``_legacy_agentic_dispatch`` so UX, session state updates,
        Chainlit messages and error handling all match exactly.
        """
        try:
            from services.llm_service import get_llm_service
            llm = get_llm_service()
        except Exception as exc:
            logger.warning(
                f"Worker LLM service unavailable, falling back to keyword dispatch: {exc}"
            )
            await self.dispatch(text)
            return {"role": "assistant", "tool": "_keyword_fallback", "args": text, "baseline": None}

        # Build the worker system prompt: shared routing rules + this
        # ONE skill body + the per-tool extraction rule. No other ops,
        # no chat_skill, no COBOL/REPORTING skills — those are reserved
        # for the chat fallback path.
        prompts_dir = Path(config.BASE_DIR) / "prompts"
        router_md = prompts_dir / "skills" / "orchestration" / "_router.md"
        rules_text = ""
        if router_md.exists():
            try:
                rules_text = router_md.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(f"Could not read {router_md}: {exc}")

        skill_body = self._skill_bodies.get(op.id, "")
        instructions = self._agentic.get("system_prompt", "")

        worker_prefix = self._load_worker_instruction(op_id=op.id, handler=op.handler)
        if self._last_router_args:
            worker_prefix += (
                f"\nRouter-extracted argument hint: '{self._last_router_args}'. "
                "Use this unless the conversation clearly indicates a "
                "different value.\n"
            )

        system_prompt_parts = [worker_prefix]
        if rules_text:
            system_prompt_parts.append(rules_text)
        if skill_body:
            system_prompt_parts.append(
                f"# ── {op.id}_skill ──\n\n{skill_body}"
            )
        if instructions:
            system_prompt_parts.append(instructions)
        system_prompt = "\n\n".join(system_prompt_parts)

        tool_schemas = self._get_single_tool_schema(op.id)

        # Build message list — same shape as legacy path so the LLM's
        # pronoun resolution behaves identically.
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        max_history = int(self._agentic.get("max_history_turns", 10))
        if conversation_history:
            for turn in conversation_history[-max_history:]:
                role = turn.get("role", "user")
                body = turn.get("content", "")
                if role in ("user", "assistant") and body:
                    messages.append({"role": role, "content": body})
        messages.append({"role": "user", "content": text})

        logger.info(
            f"Worker call: op='{op.id}' system={len(system_prompt)} chars, "
            f"tools=1 (vs legacy ~{len(self._get_skill_system_prompt())} chars, "
            f"{len(self._get_tool_schemas())} tools)"
        )

        max_iters = int(self._agentic.get("max_iterations", 10))
        args_str = ""
        for iteration in range(max_iters):
            try:
                assistant_msg = await llm.chat_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                )
            except Exception as exc:
                logger.warning(
                    f"Worker LLM tool-call failed (iteration {iteration}), "
                    f"falling back to keyword dispatch: {exc}"
                )
                await self.dispatch(text)
                return {"role": "assistant", "tool": "_keyword_fallback", "args": text, "baseline": None}

            tool_calls = assistant_msg.get("tool_calls")

            # No tool call → mirror legacy behaviour exactly.
            if not tool_calls:
                llm_text = (assistant_msg.get("content") or "").strip()
                if _looks_like_code_question(text):
                    logger.info(
                        "Worker: no tool call, code/domain question → chat handler"
                    )
                    await self._dispatch_fallback(text)
                elif llm_text:
                    logger.info("Worker: no tool call → LLM text response")
                    import chainlit as cl
                    msg = cl.Message(content="")
                    await msg.send()
                    try:
                        for chunk in _stream_chunks(llm_text, self._stream_chunk_size):
                            await msg.stream_token(chunk)
                    except Exception as stream_exc:
                        logger.warning(
                            f"Worker stream replay failed: {stream_exc}"
                        )
                        msg.content = llm_text
                    else:
                        msg.content = llm_text
                    await msg.update()
                else:
                    logger.info("Worker: no tool call, no text → chat fallback")
                    await self._dispatch_fallback(text)
                return {"role": "assistant", "tool": None, "args": "", "baseline": None}

            messages.append(assistant_msg)

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                tc_id = tc.get("id", "")

                handler = self._registry.get(tool_name)
                if handler is None:
                    logger.warning(
                        f"Worker: LLM called unknown tool '{tool_name}'. Ignoring."
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Error: unknown tool '{tool_name}'.",
                    })
                    continue

                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    parsed = {}
                schema_cfg = self._agentic.get("tool_schema", {})
                arg_param = schema_cfg.get("arg_parameter_name", "args")
                args_str = parsed.get(arg_param, "")

                # Hint fallback: if the worker LLM didn't provide args
                # but the router did, use the router's extraction.
                if not args_str and self._last_router_args:
                    args_str = self._last_router_args

                logger.info(
                    f"Worker [{iteration}]: tool='{tool_name}' args='{args_str}'"
                )

                try:
                    op_lookup = self._operations.get(tool_name) or self._handler_ops.get(tool_name)
                    if op_lookup and op_lookup.args:
                        await handler(args_str)
                    else:
                        await handler()
                    tool_result = f"Tool '{tool_name}' executed successfully."
                except Exception as exc:
                    logger.exception(f"Worker handler '{tool_name}' raised: {exc}")
                    tool_result = f"Tool '{tool_name}' failed: {exc}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result,
                })

            first_tc = tool_calls[0].get("function", {})
            called_tool = first_tc.get("name", "")
            detected_baseline = self._extract_baseline(args_str) or self._extract_baseline(text)
            return {
                "role": "assistant",
                "tool": called_tool,
                "args": args_str,
                "baseline": detected_baseline,
            }

        # Should not reach here — max_iters exhausted with no return.
        return {"role": "assistant", "tool": None, "args": "", "baseline": None}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_baseline(self, text: str) -> Optional[str]:
        """Extract first baseline name (e.g. P02070-HPPL486P) from text.

        Matches case-insensitively but returns the canonical upper-case
        form so handlers, file paths, KB IDs and session keys stay
        consistent with the historical behaviour.
        """
        m = _BASELINE_RE.search(text or "")
        return m.group(0).upper() if m else None

    async def _invoke_operation(
        self, op: Operation, args: str, source: str = "command"
    ) -> None:
        """Validate args + invoke the registered handler for ``op``."""
        validation_error = self._validate_args(op, args)
        if validation_error:
            logger.info(
                f"Orchestrator: '{op.id}' arg validation failed → "
                f"{validation_error}"
            )
            # Defer to the handler so the user sees the same usage hint as
            # before (existing handlers already check for empty args).

        handler = self._registry.get(op.handler)
        if handler is None:
            logger.error(
                f"Orchestrator: handler '{op.handler}' not registered for "
                f"operation '{op.id}'. Falling back to chat."
            )
            await self._dispatch_fallback(args or op.id)
            return

        logger.info(
            f"Orchestrator [{source}]: '{op.id}' → handler '{op.handler}'"
            + (f" args='{args}'" if args else "")
        )
        try:
            if op.args:
                await handler(args)
            else:
                await handler()
        except Exception as exc:  # noqa: BLE001 — last-line-of-defence
            logger.exception(f"Handler '{op.handler}' raised: {exc}")
            await self._dispatch_fallback(
                f"The previous command failed unexpectedly: {exc}"
            )

    def _match_nl_intent(
        self, text: str
    ) -> Optional[tuple]:
        """Detect an operation request in free-form text.

        Strategy (no LLM call):
        1. Try to extract a baseline name (full ``Pxxxxx-PROGRAM`` form).
        2. Scan the text for any operation keyword (or alias) declared in
           the skill file.
        3. If both are found → return ``(operation, baseline_args)`` so the
           orchestrator can execute the operation directly.

        This keeps natural-language requests like
        *"please copy the baseline P02070-HPPL486P"* working as actions,
        while pure questions (no operation keyword OR no baseline) still
        fall through to the chat fallback.
        """
        baseline = self._extract_baseline(text)
        if not baseline:
            return None

        op = self._extract_operation(text)
        if op is None:
            return None

        return op, baseline

    @staticmethod
    def _extract_baseline(text: str) -> Optional[str]:
        """Return the first full baseline name found in ``text``.

        Matches case-insensitively; returns the canonical upper-case form.
        """
        match = _BASELINE_RE.search(text)
        return match.group(0).upper() if match else None

    def _extract_operation(self, text: str) -> Optional[Operation]:
        """Find an operation keyword anywhere in ``text``.

        We word-boundary match each known command/alias so substrings like
        ``copying`` won't accidentally trigger ``copy``. Multi-token aliases
        from ``intent_patterns`` (e.g. ``"create branch"``) are also
        considered.
        """
        lowered = " " + text.lower() + " "
        # Single-word command keywords (and aliases).
        for keyword, op in self._operations.items():
            if op.is_fallback:
                continue
            # Build a word-boundary pattern around the keyword so that
            # "copied" / "copying" do NOT match the "copy" keyword.
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return op
        # Phrase hints from intent patterns (best-effort).
        for op in self._operations.values():
            if op.is_fallback:
                continue
            for phrase in op.intent_patterns or []:
                # Only consider multi-word phrases here (single-word ones
                # were already handled above as keywords).
                token = phrase.split()[0].lower()
                if " " in phrase and token and token in lowered:
                    return op
        return None

    def _validate_args(self, op: Operation, args: str) -> Optional[str]:
        """Lightweight regex validation for the first declared argument.

        Returns an error message string on failure, or ``None`` on success.
        Existing handlers still perform their own validation; this is purely
        an early signal for logging.
        """
        if not op.args:
            return None

        first = op.args[0]
        if first.required and not args:
            return f"missing required argument: {first.name}"

        if args and first.validation:
            try:
                if not re.match(first.validation, args.split()[0]):
                    return f"argument did not match pattern {first.validation}"
            except re.error as exc:
                logger.warning(f"Invalid regex for op '{op.id}': {exc}")
        return None

    async def _dispatch_fallback(self, text: str) -> None:
        """Invoke the chat fallback handler if registered."""
        if not self._fallback_op:
            logger.error("No fallback operation defined in skill file.")
            return

        handler = self._registry.get(self._fallback_op.handler)
        if handler is None:
            logger.error(
                f"Fallback handler '{self._fallback_op.handler}' is not "
                "registered. Natural-language input cannot be handled."
            )
            return

        try:
            await handler(text)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Fallback handler raised: {exc}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Return the process-wide orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# ---------------------------------------------------------------------------
# Reporting skill loader
# ---------------------------------------------------------------------------

_reporting_skill_cache: Optional[Dict[str, Any]] = None


def load_reporting_skill(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and cache the reporting workflow skill file.

    Returns the ``reporting_workflow`` dict from the YAML block in
    ``prompts/REPORTING_SKILL.md``.  The result is cached for the
    process lifetime so repeated calls are free.
    """
    global _reporting_skill_cache
    if _reporting_skill_cache is not None:
        return _reporting_skill_cache

    skill_path = path or (Path(config.BASE_DIR) / "prompts" / "REPORTING_SKILL.md")
    if not skill_path.exists():
        raise FileNotFoundError(f"Reporting skill file not found: {skill_path}")

    raw = skill_path.read_text(encoding="utf-8")
    for match in _YAML_BLOCK_RE.finditer(raw):
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            logger.warning(f"Skipping malformed YAML in {skill_path.name}: {exc}")
            continue

        wf = data.get("reporting_workflow") if isinstance(data, dict) else None
        if wf:
            _reporting_skill_cache = wf
            logger.info(
                f"Loaded reporting skill: {len(wf.get('steps', []))} steps "
                f"from {skill_path.name}"
            )
            return _reporting_skill_cache

    raise ValueError(
        f"No 'reporting_workflow' found in {skill_path}. "
        "Check the YAML block."
    )
