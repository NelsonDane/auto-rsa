"""Simple Mode — the Friends-Edition runtime switch (one codebase, one flag).

Resolved fresh on each call (cheap). Priority, first hit wins:

1. ``RSA_SIMPLE_MODE`` env (1/0/true/false) — operator/testing override.
2. ``creds/simple_mode.flag`` sentinel file — GUI toggle, persists across
   restarts (mirrors the license-bypass flag exactly).
3. Build default (``_keys.SIMPLE_MODE_DEFAULT``) — the friend build ships
   this True; the pro build leaves it False.

Simple Mode HIDES advanced surfaces (Diagnostics, Ledger, Trade-beta,
Signals, run-settings, notifications, backups, and the license-bypass
toggle) so a friend sees a small, low-troubleshooting app — and never
sees engine internals, which also serves the anti-reverse-engineering
goal at the UI layer. It removes UI, not capability: Trade, Balances,
Credentials, and License stay.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

_ENV = "RSA_SIMPLE_MODE"
_FLAG_PATH = Path(__file__).resolve().parents[3] / "creds" / "simple_mode.flag"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_state() -> bool | None:
    raw = os.getenv(_ENV, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def _flag_active() -> bool:
    try:
        return _FLAG_PATH.is_file()
    except OSError:
        return False


def _build_default() -> bool:
    try:
        from src.license import _keys  # noqa: PLC0415

        return bool(getattr(_keys, "SIMPLE_MODE_DEFAULT", False))
    except Exception:
        return False


def simple_mode() -> bool:
    """Whether Simple Mode is in effect. Env overrides sentinel overrides build."""
    env = _env_state()
    if env is not None:
        return env
    if _flag_active():
        return True
    return _build_default()


def simple_mode_flag_path() -> Path:
    """Path to the sentinel file (for the GUI toggle)."""
    return _FLAG_PATH


def set_simple_mode(*, enabled: bool) -> None:
    """Create or remove the sentinel file. Idempotent. The env override,
    if set, still wins over this."""
    if enabled:
        _FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FLAG_PATH.write_text(
            "Presence of this file forces Simple Mode (Friends Edition UI) on.\n"
            "Delete to return to the full interface.\n",
            encoding="utf-8",
        )
    else:
        with contextlib.suppress(FileNotFoundError):
            _FLAG_PATH.unlink()
