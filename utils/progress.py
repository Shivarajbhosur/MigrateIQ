"""
ProgressCard
============

Live-updating progress message for long-running operations.

Replaces the old "Still ...(Ns)" heartbeat spam with a **single Chainlit
message that updates in place**. The session stays active exactly as
before — only the visual presentation changes.

Style: A single card with header, subject (baseline name), a blue graphic
progress bar, percentage, elapsed time, and a status line. The card is pure
Markdown so it does not affect the existing app CSS or welcome layout.

Usage
-----

    from utils.progress import ProgressCard

    async with ProgressCard("Step 1: Copy Baseline", baseline, interval=10,
                            eta_seconds=120) as card:
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, work_fn)
        await card.wait_for(future, status="Copying input files...")
        success, result = await future
        if success:
            await card.complete("Copy complete")
        else:
            await card.fail(result.get("message", "Failed"))

The card will:
  * send ONE message on enter
  * update it every ``interval`` seconds while the future is running
  * flip to ✅ green on ``complete()`` or ❌ red on ``fail()``
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import chainlit as cl


# ----------------------------------------------------------------------
# Bar rendering
# ----------------------------------------------------------------------

_BLOCK_FILLED = "🟦"
_BLOCK_EMPTY = "⬛"
_BAR_WIDTH = 16


def _render_bar(pct: int) -> str:
    pct = max(0, min(100, int(pct)))
    filled = int(round(pct / 100 * _BAR_WIDTH))
    return _BLOCK_FILLED * filled + _BLOCK_EMPTY * (_BAR_WIDTH - filled)


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


# ----------------------------------------------------------------------
# ProgressCard
# ----------------------------------------------------------------------


class ProgressCard:
    """Async context manager that owns a single live-updating Chainlit
    message.

    Heartbeat semantics are identical to the previous implementation
    (``await asyncio.sleep(interval)`` while the future is not done) so
    the user session stays active in exactly the same way.
    """

    def __init__(
        self,
        title: str,
        subject: str = "",
        interval: int = 10,
        eta_seconds: int = 120,
        icon: str = "🔄",
    ) -> None:
        self.title = title
        self.subject = subject
        self.interval = max(1, int(interval))
        self.eta_seconds = max(10, int(eta_seconds))
        self.icon = icon
        self._msg: Optional[cl.Message] = None
        self._start: float = 0.0
        self._status: str = "Starting..."
        self._finalised: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ProgressCard":
        self._start = time.monotonic()
        self._msg = cl.Message(content=self._render(0, self._status))
        await self._msg.send()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        # If an exception escaped, mark the card as failed so the user
        # sees an explicit terminal state instead of a dangling spinner.
        if exc is not None and not self._finalised:
            try:
                await self.fail(f"Unexpected error: {exc}")
            except Exception:  # noqa: BLE001 — never raise from __aexit__
                pass
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        """Update the status line shown on the next tick."""
        self._status = status

    async def wait_for(
        self, future: Any, status: Optional[str] = None
    ) -> None:
        """Pump heartbeats while ``future`` is running.

        Mirrors the previous ``while not future.done(): sleep(interval)``
        pattern so session keep-alive behaviour is unchanged.
        """
        if status:
            self._status = status
        while not future.done():
            await asyncio.sleep(self.interval)
            if not future.done():
                await self._tick()

    async def complete(self, summary: str = "Done") -> None:
        """Flip the card to the success state and stop ticking."""
        self._finalised = True
        elapsed = time.monotonic() - self._start
        await self._update(self._render(100, summary, done=True, success=True, elapsed=elapsed))

    async def fail(self, error: str = "Failed") -> None:
        """Flip the card to the failure state and stop ticking."""
        self._finalised = True
        elapsed = time.monotonic() - self._start
        pct = self._estimate_pct(elapsed)
        await self._update(self._render(pct, error, done=True, success=False, elapsed=elapsed))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        elapsed = time.monotonic() - self._start
        pct = self._estimate_pct(elapsed)
        await self._update(self._render(pct, self._status, elapsed=elapsed))

    async def _update(self, content: str) -> None:
        if self._msg is None:
            return
        try:
            self._msg.content = content
            await self._msg.update()
        except Exception:
            # Never let UI rendering break the running operation.
            pass

    def _estimate_pct(self, elapsed: float) -> int:
        """Time-based estimate; capped at 90% until ``complete()``.

        We have no real progress signal from PowerShell / dotnet, so the
        bar is an indicator of *time spent vs expected*, not real work
        done. Capping at 90% prevents the bar from sitting at 100% while
        the operation is still running.
        """
        pct = int(elapsed / self.eta_seconds * 100)
        return max(2, min(90, pct))

    def _render(
        self,
        pct: int,
        status: str,
        done: bool = False,
        success: bool = True,
        elapsed: Optional[float] = None,
    ) -> str:
        if done:
            icon = "✅" if success else "❌"
        else:
            icon = self.icon

        bar = _render_bar(pct)
        elapsed_str = _fmt_time(elapsed if elapsed is not None else 0)
        subject_line = f"`{self.subject}`\n\n" if self.subject else "\n"

        return (
            f"{icon} **{self.title}**\n\n"
            f"{subject_line}"
            f"**Progress**  `{pct:3d}%`  •  `{elapsed_str}` elapsed\n\n"
            f"{bar}\n\n"
            f"_{status}_"
        )
