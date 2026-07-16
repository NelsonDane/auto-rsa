"""Pre-flight warnings shown on the LIVE-confirm screen.

Fast and non-blocking: the point is to surface, *before* the operator
types EXECUTE, the things that will otherwise surprise them mid-run — a
broker whose saved login session has expired (a 2FA prompt will appear
and the run blocks until answered), and a stale run lock that will refuse
the run outright. It never blocks the run and never raises; a check it
can't perform is simply omitted.
"""

from __future__ import annotations

from typing import NamedTuple

from src import session_state
from src.gui.core import diagnostics

WARN = "WARN"


class PreflightItem(NamedTuple):
    """One pre-flight heads-up."""

    level: str
    message: str

    @property
    def icon(self) -> str:
        """Emoji for this item."""
        return "⚠️"


def _health_by_broker() -> dict[str, list[str]]:
    """Map broker key -> the health strings of its session artifact(s).

    Prefers the cached audit snapshot (fast); falls back to a fresh audit
    only if nothing is cached. Best-effort.
    """
    out: dict[str, list[str]] = {}

    def _add(broker: object, health: object) -> None:
        key = str(broker or "").strip()
        if key:
            out.setdefault(key, []).append(str(health))

    try:
        snap = session_state.load_last_audit()
    except Exception:  # noqa: BLE001
        snap = []
    if snap:
        for row in snap:
            _add(row.get("broker"), row.get("health"))
        return out
    try:
        for rec in session_state.audit(persist=True):
            _add(rec.broker, rec.health)
    except Exception:  # noqa: BLE001
        pass
    return out


def preflight_for_run(broker_keys: list[str]) -> list[PreflightItem]:
    """Non-blocking heads-up for a LIVE run over ``broker_keys``.

    ``broker_keys`` must be the RESOLVED list (no ``"all"`` sentinel).
    Returns an empty list when everything looks ready.
    """
    items: list[PreflightItem] = []

    try:
        health = _health_by_broker()
    except Exception:  # noqa: BLE001
        health = {}
    expired = [
        bk
        for bk in broker_keys
        if any(h == session_state.RED for h in health.get(bk, []))
    ]
    for bk in expired:
        items.append(
            PreflightItem(
                WARN,
                f"**{bk}** — saved login session looks expired; expect a "
                "login / 2FA prompt during the run (it will pause until you "
                "answer it in the Activity panel).",
            ),
        )

    try:
        lock = diagnostics.inspect_run_lock()
    except Exception:  # noqa: BLE001
        lock = None
    if lock and lock.get("stale"):
        items.append(
            PreflightItem(
                WARN,
                "A stale run lock left by a dead process is present — if the "
                "run won't start, clear it in the 🩺 Diagnostics tab.",
            ),
        )

    return items
