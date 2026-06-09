"""
Workflow Tool Registry
======================

Thin registry that maps operation names declared in
``prompts/WORKFLOW_ORCHESTRATION_SKILL.md`` to their executable Python
callables.

Why a registry?
---------------
* Existing handler functions live in ``app.py`` and are tightly coupled to
  Chainlit primitives (``cl.Message``, ``cl.Action``, action callbacks,
  per-message heartbeats).  Moving them would change behaviour and risk
  regressions.  Instead, ``app.py`` *registers* its existing handlers under
  the names declared in the skill file at import time.
* The orchestrator only knows the registry — it has zero hard-coded command
  names.  Adding a new operation requires only:
    1. A new entry in the skill file.
    2. ``register("<name>", <handler>)`` from somewhere (usually ``app.py``).

The handlers themselves are **not modified** by this module.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional

from utils.logger import get_logger


logger = get_logger("workflow_tools")


# A handler accepts the raw argument string from the user (everything after
# the command keyword) and returns nothing — it sends its own messages via
# Chainlit.  Existing ``handle_*`` functions in ``app.py`` already match this
# signature, so they can be registered as-is.
Handler = Callable[[str], Awaitable[None]]
NoArgHandler = Callable[[], Awaitable[None]]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Process-wide registry of operation handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable] = {}

    def register(self, name: str, handler: Callable) -> None:
        """Register (or replace) a handler under ``name``.

        ``name`` should match the ``handler:`` field of an operation in the
        skill file.  Re-registering is allowed and will log a debug notice.
        """
        if not name:
            raise ValueError("Handler name must be a non-empty string.")
        if not callable(handler):
            raise TypeError(f"Handler for '{name}' must be callable.")
        if name in self._handlers:
            logger.debug(f"Replacing handler '{name}'")
        self._handlers[name] = handler
        logger.debug(f"Registered handler '{name}' → {handler.__qualname__}")

    def get(self, name: str) -> Optional[Callable]:
        return self._handlers.get(name)

    def has(self, name: str) -> bool:
        return name in self._handlers

    def names(self) -> list[str]:
        return sorted(self._handlers.keys())


# Module-level singleton — import from anywhere.
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Return the global tool registry."""
    return _registry


def register(name: str, handler: Callable) -> None:
    """Convenience: register a handler with the global registry."""
    _registry.register(name, handler)


def register_many(mapping: Dict[str, Callable]) -> None:
    """Register multiple ``name → handler`` pairs at once."""
    for name, handler in mapping.items():
        _registry.register(name, handler)
