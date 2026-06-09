"""
Context Builder Service

Gathers code/knowledge context for the chat agent: COBOL main + sub-programs
(via CALL parsing), target-language source / record files, similar past fixes
from the knowledge base, and any user-supplied snippet/diff.

This service is additive — it only consumes existing services
(``CobolService``, ``CodebaseService``, ``KnowledgeBaseService``) and never
mutates them. All failures are downgraded to "no result" so the chat layer
can still respond.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.cobol_service import get_cobol_service
from services.codebase_service import get_codebase_service
from services.knowledge_base_service import get_kb_service
from utils.logger import get_logger

import config

logger = get_logger("context_builder_service")


# Match COBOL CALL statements: CALL "HPPL050P" or CALL 'HPPL050P'.
_CALL_PATTERN = re.compile(r"""CALL\s+["']([A-Z][A-Z0-9]{2,9})["']""", re.IGNORECASE)

# Target-language file extensions we will surface as "main" / "record" files.
# Kept in sync with the supported extensions in `_fetch_target`.
_TARGET_EXTS = (".cs", ".java", ".py")

# Folders skipped when scanning the SSAB.OX repo for direct lookups.
# Mirrors `CodebaseService.EXCLUDE_FOLDERS` so the fallback behaves the same
# as the ingest pipeline and does not pick up build artefacts.
_REPO_EXCLUDE_FOLDERS = {
    "bin", "obj", "packages", ".git", ".vs",
    "node_modules", "TestResults", "Debug", "Release",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProgramArtifact:
    """A single COBOL or target-language file resolved from KB or live disk."""

    program_name: str = ""
    file_path: str = ""
    code: str = ""

    def has_code(self) -> bool:
        return bool(self.code and self.code.strip())


@dataclass
class SimilarFixArtifact:
    pr_id: int = 0
    baseline: str = ""
    title: str = ""
    files_changed: List[str] = field(default_factory=list)
    code_diff: str = ""
    score: float = 0.0


@dataclass
class ContextBundle:
    """All context gathered for one chat turn."""

    program_name: Optional[str] = None
    baseline_name: Optional[str] = None
    cobol_main: ProgramArtifact = field(default_factory=ProgramArtifact)
    cobol_subprograms: List[ProgramArtifact] = field(default_factory=list)
    target_main: ProgramArtifact = field(default_factory=ProgramArtifact)
    target_record: ProgramArtifact = field(default_factory=ProgramArtifact)
    similar_fixes: List[SimilarFixArtifact] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.cobol_main.has_code()
            or self.target_main.has_code()
            or self.similar_fixes
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ContextBuilderService:
    """Lazy, singleton context builder used by the chat agent."""

    def __init__(self) -> None:
        self._cobol = None
        self._codebase = None
        self._kb = None
        # Cached program_id (upper-case, no extension) -> list of repo paths.
        # Built on first miss, refreshed when the repo mtime changes so newly
        # added / renamed files are picked up without restarting the app.
        self._repo_index: Optional[Dict[str, List[str]]] = None
        self._repo_index_mtime: float = 0.0

    # Lazy properties so tests / partial deployments don't need every backend.
    @property
    def cobol(self):
        if self._cobol is None:
            self._cobol = get_cobol_service()
        return self._cobol

    @property
    def codebase(self):
        if self._codebase is None:
            self._codebase = get_codebase_service()
        return self._codebase

    @property
    def kb(self):
        if self._kb is None:
            self._kb = get_kb_service()
        return self._kb

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(
        self,
        program_name: Optional[str],
        baseline_name: Optional[str],
        query: str,
        limits: Dict[str, int],
    ) -> ContextBundle:
        """Build the full context bundle for one chat turn (best-effort)."""
        bundle = ContextBundle(
            program_name=program_name,
            baseline_name=baseline_name,
        )

        if program_name:
            try:
                bundle.cobol_main = self._fetch_cobol(
                    program_name,
                    int(limits.get("cobol_main_chars", 6000)),
                )
            except Exception as exc:
                logger.warning(f"Failed to fetch COBOL main for {program_name}: {exc}")

            try:
                bundle.cobol_subprograms = self._fetch_subprograms(
                    bundle.cobol_main,
                    int(limits.get("max_subprograms", 3)),
                    int(limits.get("cobol_subprogram_chars", 1500)),
                )
            except Exception as exc:
                logger.warning(f"Failed to fetch sub-programs for {program_name}: {exc}")

            try:
                bundle.target_main, bundle.target_record = self._fetch_target(
                    program_name,
                    int(limits.get("target_main_chars", 6000)),
                    int(limits.get("target_record_chars", 2000)),
                )
            except Exception as exc:
                logger.warning(f"Failed to fetch target code for {program_name}: {exc}")

        try:
            bundle.similar_fixes = self._fetch_similar_fixes(
                program_name=program_name,
                query=query,
                max_fixes=int(limits.get("max_similar_fixes", 3)),
                diff_chars=int(limits.get("similar_fix_chars", 1500)),
            )
        except Exception as exc:
            logger.warning(f"Failed to fetch similar fixes: {exc}")

        return bundle

    # ------------------------------------------------------------------
    # COBOL
    # ------------------------------------------------------------------

    def _fetch_cobol(self, program_name: str, max_chars: int) -> ProgramArtifact:
        artifact = ProgramArtifact(program_name=program_name)

        # Exact program-name lookup is fastest and most accurate.
        result = self.cobol.get_by_program_name(program_name)
        if not result:
            results = self.cobol.search_hybrid(program_name, n_results=1)
            if results:
                # Hybrid search places content under "content"; normalise it.
                first = results[0]
                if "document" not in first and "content" in first:
                    first = {**first, "document": first.get("content", "")}
                result = first

        if not result:
            return artifact

        meta = result.get("metadata", {}) or {}
        artifact.file_path = (
            meta.get("full_path")
            or meta.get("relative_path")
            or f"{program_name}.COB"
        )
        artifact.code = _truncate(result.get("document", "") or "", max_chars)
        return artifact

    def _fetch_subprograms(
        self,
        main: ProgramArtifact,
        max_count: int,
        max_chars: int,
    ) -> List[ProgramArtifact]:
        if not main.has_code() or max_count <= 0:
            return []

        called: List[str] = []
        seen = {main.program_name.upper()}
        for match in _CALL_PATTERN.finditer(main.code):
            name = match.group(1).upper()
            if name in seen:
                continue
            seen.add(name)
            called.append(name)
            if len(called) >= max_count:
                break

        subs: List[ProgramArtifact] = []
        for name in called:
            try:
                sub = self._fetch_cobol(name, max_chars)
            except Exception as exc:
                logger.debug(f"Could not load sub-program {name}: {exc}")
                continue
            if sub.has_code():
                subs.append(sub)
        return subs

    # ------------------------------------------------------------------
    # Target language (C# / Java / Python)
    # ------------------------------------------------------------------

    def _fetch_target(
        self,
        program_name: str,
        main_chars: int,
        record_chars: int,
    ) -> Tuple[ProgramArtifact, ProgramArtifact]:
        main_art = ProgramArtifact(program_name=program_name)
        record_art = ProgramArtifact(program_name=program_name)

        results = self.codebase.search_hybrid(program_name, n_results=5) or []

        # KB-driven path: walk hybrid hits and pick a main + record file by
        # name convention. ``_read_live_or_kb`` already prefers the live file
        # on disk so user edits to indexed programs are reflected immediately.
        for result in results:
            meta = result.get("metadata", {}) or {}
            file_path = meta.get("full_path") or meta.get("relative_path") or ""
            if not file_path:
                continue
            # Only treat a hybrid hit as the right program when the filename
            # actually matches the requested program ID — otherwise semantic
            # search would happily return e.g. ``J3015123.cs`` for a query of
            # ``OJ011533`` and the caller would never see the on-disk file.
            if not self._filename_matches(file_path, program_name):
                continue

            content = self._read_live_or_kb(file_path, result)
            lower_name = os.path.basename(file_path).lower()
            is_record = "record" in lower_name
            is_supported = lower_name.endswith(_TARGET_EXTS)

            if is_record and not record_art.has_code():
                record_art.file_path = file_path
                record_art.code = _truncate(content, record_chars)
            elif (
                is_supported
                and not is_record
                and not main_art.has_code()
            ):
                main_art.file_path = file_path
                main_art.code = _truncate(content, main_chars)

            if main_art.has_code() and record_art.has_code():
                break

        # Filesystem fallback: covers brand-new programs that have not yet
        # been re-ingested into the codebase KB. We only read files that the
        # KB missed, so behaviour for already-indexed programs is unchanged.
        if not main_art.has_code() or not record_art.has_code():
            for fs_path in self._lookup_program_files(program_name):
                lower_name = os.path.basename(fs_path).lower()
                is_record = "record" in lower_name
                is_supported = lower_name.endswith(_TARGET_EXTS)
                if is_record and not record_art.has_code():
                    record_art.file_path = fs_path
                    record_art.code = _truncate(
                        self._read_disk_file(fs_path), record_chars
                    )
                elif (
                    is_supported
                    and not is_record
                    and not main_art.has_code()
                ):
                    main_art.file_path = fs_path
                    main_art.code = _truncate(
                        self._read_disk_file(fs_path), main_chars
                    )
                if main_art.has_code() and record_art.has_code():
                    break

        return main_art, record_art

    # ------------------------------------------------------------------
    # Filesystem fallback helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filename_matches(file_path: str, program_name: str) -> bool:
        """True when the file's stem equals or starts with the program ID.

        Matches e.g. ``Oj011533.cs`` and ``Oj011533.record.cs`` for an
        ``OJ011533`` query, case-insensitive.
        """
        stem = os.path.splitext(os.path.basename(file_path))[0].lower()
        program = (program_name or "").lower()
        if not stem or not program:
            return False
        # Strip trailing ``.record`` qualifier when comparing the stem.
        head = stem.split(".", 1)[0]
        return head == program

    @staticmethod
    def _read_disk_file(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read()
        except OSError as exc:
            logger.debug(f"Direct read failed for {path}: {exc}")
            return ""

    def _lookup_program_files(self, program_name: str) -> List[str]:
        """Return repo files whose stem matches ``program_name``.

        The repo is scanned once and the result cached. The cache is
        rebuilt only when the repo root's mtime changes (cheap stat), so
        adding a new ``.cs`` file is reflected without restarting the app.
        Returns an empty list when the repo path is not configured / does
        not exist.
        """
        repo = getattr(config, "SSAB_OX_REPO_PATH", "") or ""
        if not repo or not os.path.isdir(repo):
            return []

        try:
            current_mtime = os.path.getmtime(repo)
        except OSError:
            current_mtime = 0.0

        if self._repo_index is None or current_mtime != self._repo_index_mtime:
            self._repo_index = self._build_repo_index(repo)
            self._repo_index_mtime = current_mtime

        return self._repo_index.get(program_name.upper(), [])

    @staticmethod
    def _build_repo_index(repo_path: str) -> Dict[str, List[str]]:
        """Walk ``repo_path`` once, return ``{PROGRAM_ID: [file paths]}``.

        Only files with target-language extensions are indexed; build
        folders are skipped. Cost is one walk per repo-mtime change.
        """
        index: Dict[str, List[str]] = {}
        for root, dirs, files in os.walk(repo_path):
            # Skip build / VCS folders in-place for a faster walk.
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {f.lower() for f in _REPO_EXCLUDE_FOLDERS}
            ]
            for name in files:
                lower = name.lower()
                if not lower.endswith(_TARGET_EXTS):
                    continue
                stem = os.path.splitext(name)[0]
                head = stem.split(".", 1)[0].upper()
                index.setdefault(head, []).append(os.path.join(root, name))
        logger.info(
            f"ContextBuilder filesystem index built: "
            f"{len(index)} program IDs across {sum(len(v) for v in index.values())} files"
        )
        return index

    @staticmethod
    def _read_live_or_kb(file_path: str, kb_result: Dict[str, Any]) -> str:
        """Prefer the live filesystem version; fall back to the KB document."""
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    return fh.read()
            except OSError as exc:
                logger.debug(f"Live read failed for {file_path}: {exc}")
        return kb_result.get("content") or kb_result.get("document", "") or ""

    # ------------------------------------------------------------------
    # Knowledge base — similar past fixes
    # ------------------------------------------------------------------

    def _fetch_similar_fixes(
        self,
        program_name: Optional[str],
        query: str,
        max_fixes: int,
        diff_chars: int,
    ) -> List[SimilarFixArtifact]:
        if max_fixes <= 0:
            return []

        kb_query_parts = [p for p in (program_name, (query or "")[:200]) if p]
        if not kb_query_parts:
            return []
        kb_query = " ".join(kb_query_parts)

        # Both keyword and semantic search return ``document`` directly, which
        # is what we want for the diff. ``search_hybrid`` ranks well but does
        # not include documents — so we pick the search variant that gives us
        # the diff content for the given query type.
        if program_name:
            results = self.kb.search_keyword(kb_query, n_results=max_fixes) or []
        else:
            results = self.kb.search_similar(kb_query, n_results=max_fixes) or []

        fixes: List[SimilarFixArtifact] = []
        for result in results:
            meta = result.get("metadata", {}) or {}
            files_changed_str = meta.get("files_changed", "") or ""
            files = [f for f in files_changed_str.split(",") if f]
            try:
                pr_id = int(meta.get("pr_id", 0) or 0)
            except (TypeError, ValueError):
                pr_id = 0
            try:
                score = float(result.get("score", 0) or 0)
            except (TypeError, ValueError):
                score = 0.0
            fixes.append(
                SimilarFixArtifact(
                    pr_id=pr_id,
                    baseline=meta.get("baseline", "") or "",
                    title=meta.get("title", "") or "",
                    files_changed=files,
                    code_diff=_truncate(result.get("document", "") or "", diff_chars),
                    score=score,
                )
            )
        return fixes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_context_builder: Optional[ContextBuilderService] = None


def get_context_builder() -> ContextBuilderService:
    """Return the process-wide context builder."""
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilderService()
    return _context_builder
