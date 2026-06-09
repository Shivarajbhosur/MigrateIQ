"""
Chat Agent

Singleton natural-language chat agent for the validation app. Routes free-form
user messages to the LLM with COBOL/{TARGET_LANGUAGE} context gathered from
the knowledge base and the live codebase.

This agent is additive: it does not modify any existing agent or service. All
prompt text lives in:

* ``prompts/chat_skill.md`` — generic chat behaviour (language-agnostic)
* ``prompts/chat_prompts.yaml`` — templates, limits, fallbacks
* ``prompts/COBOL_TO_<LANG>_SKILL.MD`` — domain skill, picked by
  ``TARGET_LANGUAGE`` in ``.env`` (default ``csharp``).

To switch target language to e.g. Java:

1. Set ``TARGET_LANGUAGE=java`` in ``.env``.
2. Add ``prompts/COBOL_TO_JAVA_SKILL.MD``.

No code changes required.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

import config
from services.context_builder_service import (
    ContextBundle,
    get_context_builder,
)
from services.llm_service import get_llm_service
from utils.logger import get_logger

logger = get_logger("chat_agent")


# Default NL detection patterns for program / baseline IDs. Overridden at
# ChatAgent.__init__ from prompts/chat_prompts.yaml -> patterns.{baseline,
# program}. Kept here as safe fallbacks so the agent still functions if the
# yaml entry is missing. Compiled case-insensitive; captured values are
# normalised to upper-case by callers since on-disk IDs are upper.
_BASELINE_RE = re.compile(r"\bP\d{4,6}-([A-Z]{1,6}\d{2,8}[A-Z]?)\b", re.IGNORECASE)
_PROGRAM_RE = re.compile(r"\b([A-Z]{1,6}\d{2,8}[A-Z]?)\b", re.IGNORECASE)


def _reconfigure_patterns(baseline: Optional[str], program: Optional[str]) -> None:
    """Recompile module-level pattern regexes from yaml config (case-insensitive)."""
    global _BASELINE_RE, _PROGRAM_RE
    if baseline:
        _BASELINE_RE = re.compile(baseline, re.IGNORECASE)
    if program:
        _PROGRAM_RE = re.compile(program, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ChatTurn:
    """One past message in the chat history."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class ChatResponse:
    """Result of a single chat turn."""

    text: str
    program_name: Optional[str] = None
    baseline_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ChatAgent:
    """Free-form chat agent. Singleton — use :func:`get_chat_agent`."""

    def __init__(self) -> None:
        self._llm = get_llm_service()
        self._context_builder = get_context_builder()
        self._config = self._load_yaml()

        # Override default NL patterns from yaml (silently ignored if absent).
        patterns = self._config.get("patterns", {}) or {}
        _reconfigure_patterns(patterns.get("baseline"), patterns.get("program"))

        self._target_language = (
            os.getenv("TARGET_LANGUAGE", "csharp") or "csharp"
        ).strip().lower()

        languages = self._config.get("languages", {}) or {}
        meta = languages.get(self._target_language, {}) or {}
        self._language_name = meta.get("name", self._target_language)
        self._language_tag = meta.get("tag", self._target_language)

        self._chat_skill = self._load_skill(
            self._config.get("chat_skill_file", "")
        )
        self._domain_skill = self._load_domain_skill()

        logger.info(
            "ChatAgent initialised "
            f"(target={self._target_language}, "
            f"chat_skill={'ok' if self._chat_skill else 'missing'}, "
            f"domain_skill={'ok' if self._domain_skill else 'missing'})"
        )

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_yaml(self) -> Dict:
        path = Path(config.BASE_DIR) / "prompts" / "chat_prompts.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Chat prompts config not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _load_skill(self, relative_path: str) -> str:
        if not relative_path:
            return ""
        path = Path(config.BASE_DIR) / relative_path
        if not path.exists():
            logger.warning(f"Skill file not found: {path}")
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Failed to read skill file {path}: {exc}")
            return ""

    def _load_domain_skill(self) -> str:
        pattern = self._config.get("domain_skill_pattern", "")
        if not pattern:
            return ""
        rendered = pattern.format(
            TARGET_LANGUAGE=self._target_language,
            TARGET_LANGUAGE_UPPER=self._target_language.upper(),
            TARGET_LANGUAGE_NAME=self._language_name,
        )
        return self._load_skill(rendered)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_message: str,
        history: Optional[List[ChatTurn]] = None,
        active_program: Optional[str] = None,
        active_baseline: Optional[str] = None,
    ) -> ChatResponse:
        """Process one chat turn and return the assistant reply."""
        user_message = (user_message or "").strip()
        if not user_message:
            return ChatResponse(text="Please type a question.")

        history = history or []

        program_name, baseline_name = self._extract_targets(
            user_message, history, active_program, active_baseline
        )

        bundle = await self._context_builder.build(
            program_name=program_name,
            baseline_name=baseline_name,
            query=user_message,
            limits=self._config.get("limits", {}) or {},
        )

        if not self._llm.api_url or not self._llm.api_key:
            return ChatResponse(
                text=self._fallback("no_api"),
                program_name=program_name,
                baseline_name=baseline_name,
            )

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(user_message, history, bundle)

        try:
            response_text = await self._llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=int(self._config.get("max_tokens", 4096)),
                temperature=float(self._config.get("temperature", 0.2)),
            )
        except Exception as exc:
            logger.error(f"Chat LLM call failed: {exc}")
            return ChatResponse(
                text=self._fallback("llm_error"),
                program_name=program_name,
                baseline_name=baseline_name,
            )

        text = (response_text or "").strip() or self._fallback("llm_error")
        return ChatResponse(
            text=text,
            program_name=program_name,
            baseline_name=baseline_name,
        )

    async def chat_stream(
        self,
        user_message: str,
        history: Optional[List[ChatTurn]] = None,
        active_program: Optional[str] = None,
        active_baseline: Optional[str] = None,
        on_token=None,
    ) -> ChatResponse:
        """Streaming variant of :meth:`chat`.

        Behaviour is identical to :meth:`chat` (same prompts, same context
        bundle, same fallbacks) — the only difference is that incoming
        tokens are forwarded to ``on_token(chunk)`` as they arrive so the
        UI can render them ChatGPT/Copilot-style. The final assembled,
        whitespace-trimmed text is returned via :class:`ChatResponse` so
        the caller can persist it in history exactly as before.

        ``on_token`` may be sync or async; both are supported.
        """
        user_message = (user_message or "").strip()
        if not user_message:
            return ChatResponse(text="Please type a question.")

        history = history or []

        program_name, baseline_name = self._extract_targets(
            user_message, history, active_program, active_baseline
        )

        bundle = await self._context_builder.build(
            program_name=program_name,
            baseline_name=baseline_name,
            query=user_message,
            limits=self._config.get("limits", {}) or {},
        )

        if not self._llm.api_url or not self._llm.api_key:
            return ChatResponse(
                text=self._fallback("no_api"),
                program_name=program_name,
                baseline_name=baseline_name,
            )

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(user_message, history, bundle)

        # Detect coroutine callbacks once so the inner loop stays tight.
        import inspect
        cb_is_async = on_token is not None and inspect.iscoroutinefunction(on_token)

        parts: List[str] = []
        try:
            async for chunk in self._llm.chat_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=int(self._config.get("max_tokens", 4096)),
                temperature=float(self._config.get("temperature", 0.2)),
            ):
                if not chunk:
                    continue
                parts.append(chunk)
                if on_token is None:
                    continue
                try:
                    if cb_is_async:
                        await on_token(chunk)
                    else:
                        on_token(chunk)
                except Exception as cb_exc:
                    # Never let a UI callback break the stream.
                    logger.warning(f"Chat stream callback error: {cb_exc}")
        except Exception as exc:
            logger.error(f"Chat LLM stream failed: {exc}")
            return ChatResponse(
                text=self._fallback("llm_error"),
                program_name=program_name,
                baseline_name=baseline_name,
            )

        text = ("".join(parts)).strip() or self._fallback("llm_error")
        return ChatResponse(
            text=text,
            program_name=program_name,
            baseline_name=baseline_name,
        )

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        parts: List[str] = []
        if self._chat_skill:
            parts.append(self._render(self._chat_skill))
        if self._domain_skill:
            parts.append(self._render(self._domain_skill))
        if not parts:
            # Last-resort minimal instruction so the LLM is never given an
            # empty system prompt.
            parts.append(
                "You are an expert COBOL and "
                f"{self._language_name} engineer. Use only the provided "
                "context. Ask one focused follow-up if essential information "
                "is missing."
            )
        return "\n\n---\n\n".join(parts)

    def _build_user_prompt(
        self,
        user_message: str,
        history: List[ChatTurn],
        bundle: ContextBundle,
    ) -> str:
        sections_cfg = self._config.get("sections", {}) or {}
        limits = self._config.get("limits", {}) or {}
        max_history = int(limits.get("history_messages", 6))

        history_section = self._render_history(history, max_history)
        detected_section = self._render_detected(sections_cfg, bundle)
        cobol_section = self._render_cobol(sections_cfg, bundle)
        target_section = self._render_target(sections_cfg, bundle)
        similar_section = self._render_similar(sections_cfg, bundle)
        snippet_section = self._render_snippet(sections_cfg, user_message)

        # Hard directive: when the user pastes a snippet but we have no
        # COBOL/target source for any program, the model MUST ask for the
        # program name instead of fabricating a generic "fix".
        snippet_present = bool(snippet_section.strip())
        cobol_present = bool(cobol_section.strip())
        target_present = bool(target_section.strip())
        directive_section = ""
        if snippet_present and not cobol_present and not target_present:
            directive_section = (
                "# REQUIRED ACTION\n"
                "A code snippet was provided but NO COBOL source and NO "
                f"{self._language_name} source is available for any program. "
                "You CANNOT validate or fix the snippet without the COBOL "
                "source of truth.\n\n"
                "Your reply MUST be exactly one short follow-up question "
                "asking which program (e.g. `HPPL486P`) the snippet belongs "
                "to. Do NOT analyse the snippet. Do NOT suggest a fix. Do "
                "NOT add null checks, defensive coding, or generic advice. "
                "Ask the question and stop."
            )
        elif snippet_present and target_present:
            # The snippet is the BUG. The real file is the source of truth
            # for identifiers. Make this rule unmissable right before the
            # LLM generates output.
            directive_section = (
                "# REQUIRED BEHAVIOUR\n"
                "The user's snippet under `# User-Provided Snippet / Diff` "
                "is the BROKEN code, not a reference. Identifiers in the "
                "snippet (variable names, property names, method names) "
                f"are likely WRONG. The real {self._language_name} file "
                "shown under `# {LANG} Code` is the only source of truth "
                f"for {self._language_name} identifiers.\n\n"
                "Before writing your fix:\n"
                "1. Locate the corresponding block in the real "
                f"{self._language_name} file (search by COBOL field names).\n"
                "2. Use ONLY the identifiers from that real file.\n"
                "3. Discard snippet-only identifiers entirely.\n\n"
                "Your `### Suggested Fix` block MUST compile against the "
                f"real {self._language_name} file as-is — every identifier "
                "you write must already exist in that file (or be a COBOL "
                "field mapped to a real file identifier)."
            ).replace("{LANG}", self._language_name)

        template = self._config.get("user_template", "")
        if not template:
            # Defensive default — should not trigger in normal use.
            template = "{user_message}\n\n{cobol_section}\n\n{target_section}"

        rendered = self._render(
            template,
            user_message=user_message,
            history_section=history_section,
            detected_section=detected_section,
            cobol_section=cobol_section,
            target_section=target_section,
            similar_section=similar_section,
            snippet_section=snippet_section,
        )
        if directive_section:
            rendered = f"{directive_section}\n\n{rendered}"
        return rendered

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_history(history: List[ChatTurn], max_messages: int) -> str:
        if not history or max_messages <= 0:
            return "_(no prior messages)_"
        recent = history[-max_messages:]
        lines: List[str] = []
        for turn in recent:
            speaker = "User" if turn.role == "user" else "Assistant"
            lines.append(f"**{speaker}:** {turn.content.strip()}")
        return "\n\n".join(lines)

    def _render_detected(self, sections_cfg: Dict, bundle: ContextBundle) -> str:
        if not bundle.program_name and not bundle.baseline_name:
            return ""
        template = (sections_cfg.get("detected", {}) or {}).get("template", "")
        if not template:
            return ""
        return self._render(
            template,
            program_name=bundle.program_name or "(unknown)",
            baseline_name=bundle.baseline_name or "(unknown)",
        )

    def _render_cobol(self, sections_cfg: Dict, bundle: ContextBundle) -> str:
        main = bundle.cobol_main
        if not main.has_code():
            return ""
        template = (sections_cfg.get("cobol", {}) or {}).get("template", "")
        if not template:
            return ""

        sub_template = (sections_cfg.get("cobol_subprogram", {}) or {}).get(
            "template", ""
        )
        sub_blocks: List[str] = []
        for sub in bundle.cobol_subprograms:
            if not sub.has_code() or not sub_template:
                continue
            sub_blocks.append(
                self._render(
                    sub_template,
                    name=sub.program_name,
                    file_path=sub.file_path or "(unknown)",
                    code=sub.code,
                )
            )

        return self._render(
            template,
            cobol_file_path=main.file_path or "(unknown)",
            cobol_code=main.code,
            subprograms_block="\n\n".join(sub_blocks),
        )

    def _render_target(self, sections_cfg: Dict, bundle: ContextBundle) -> str:
        main = bundle.target_main
        record = bundle.target_record
        if not main.has_code() and not record.has_code():
            return ""
        template = (sections_cfg.get("target", {}) or {}).get("template", "")
        if not template:
            return ""

        record_template = (sections_cfg.get("target_record", {}) or {}).get(
            "template", ""
        )
        record_block = ""
        if record.has_code() and record_template:
            record_block = self._render(
                record_template,
                record_path=record.file_path or "(unknown)",
                record_code=record.code,
            )

        return self._render(
            template,
            target_file_path=main.file_path or "(unknown)",
            target_code=main.code or "_(target source not found)_",
            record_block=record_block,
        )

    def _render_similar(self, sections_cfg: Dict, bundle: ContextBundle) -> str:
        if not bundle.similar_fixes:
            return ""
        template = (sections_cfg.get("similar", {}) or {}).get("template", "")
        if not template:
            return ""
        blocks: List[str] = []
        for fix in bundle.similar_fixes:
            files = ", ".join(fix.files_changed) if fix.files_changed else "(unknown)"
            diff_section = ""
            if fix.code_diff:
                diff_section = f"\nDiff:\n```\n{fix.code_diff}\n```"
            blocks.append(
                f"- PR #{fix.pr_id} | Baseline `{fix.baseline}` | "
                f"{fix.title or '(no title)'}\n  Files: {files}{diff_section}"
            )
        return self._render(template, similar_fixes_block="\n\n".join(blocks))

    def _render_snippet(self, sections_cfg: Dict, user_message: str) -> str:
        snippet = self._extract_snippet(user_message)
        if not snippet:
            return ""
        template = (sections_cfg.get("snippet", {}) or {}).get("template", "")
        if not template:
            return ""
        return self._render(template, snippet=snippet)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render(self, template: str, **overrides: str) -> str:
        """Format ``template`` with language placeholders + caller overrides.

        Uses :class:`_SafeFormatDict` so that braces in the template that
        don't match a known variable (e.g. C# generics, JSON examples) are
        left untouched instead of raising.
        """
        values: Dict[str, str] = {
            "TARGET_LANGUAGE": self._target_language,
            "TARGET_LANGUAGE_UPPER": self._target_language.upper(),
            "TARGET_LANGUAGE_NAME": self._language_name,
            "TARGET_LANGUAGE_TAG": self._language_tag,
        }
        values.update({k: ("" if v is None else str(v)) for k, v in overrides.items()})
        return _safe_format(template, values)

    def _fallback(self, key: str) -> str:
        fallbacks = self._config.get("fallbacks", {}) or {}
        text = fallbacks.get(key, "")
        if not text:
            return "Sorry, the chat assistant is currently unavailable."
        return self._render(text)

    @staticmethod
    def _extract_targets(
        user_message: str,
        history: List[ChatTurn],
        active_program: Optional[str],
        active_baseline: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Best-effort detection of program / baseline in this turn or history."""
        program: Optional[str] = None
        baseline: Optional[str] = active_baseline

        # Latest message wins.
        baseline_match = _BASELINE_RE.search(user_message)
        if baseline_match:
            baseline = baseline_match.group(0).upper()
            program = baseline_match.group(1).upper()
        else:
            program_match = _PROGRAM_RE.search(_strip_code_blocks(user_message))
            if program_match:
                program = program_match.group(1).upper()

        # Fall back to recent user history.
        if not program:
            for turn in reversed(history[-6:]):
                if turn.role != "user":
                    continue
                bm = _BASELINE_RE.search(turn.content)
                if bm:
                    baseline = baseline or bm.group(0).upper()
                    program = bm.group(1).upper()
                    break
                pm = _PROGRAM_RE.search(_strip_code_blocks(turn.content))
                if pm:
                    program = pm.group(1).upper()
                    break

        # Fall back to the last sticky program from the chainlit session.
        if not program and active_program:
            program = active_program

        return program, baseline

    @staticmethod
    def _extract_snippet(message: str) -> str:
        """Return the first fenced code block in the message, if any."""
        match = re.search(r"```[\w-]*\n(.*?)```", message, re.DOTALL)
        return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks before scanning for identifiers (avoids
    false positives from snippets the user pasted)."""
    return re.sub(r"```.*?```", " ", text, flags=re.DOTALL)


class _SafeFormatDict(dict):
    """``str.format_map`` helper that leaves unknown ``{keys}`` untouched."""

    def __missing__(self, key):  # type: ignore[override]
        return "{" + key + "}"


def _safe_format(template: str, values: Dict[str, str]) -> str:
    if not template:
        return ""
    try:
        return template.format_map(_SafeFormatDict(values))
    except Exception as exc:
        logger.debug(f"Template format failed, returning raw template: {exc}")
        return template


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_chat_agent: Optional[ChatAgent] = None


def get_chat_agent() -> ChatAgent:
    """Return the process-wide chat agent."""
    global _chat_agent
    if _chat_agent is None:
        _chat_agent = ChatAgent()
    return _chat_agent
