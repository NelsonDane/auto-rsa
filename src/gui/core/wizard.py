"""First-run setup wizard state (Friends Edition onboarding).

The wizard runs on the friend build (Simple Mode) until setup is marked
complete via ``creds/setup_complete.flag``. It's resumable: the current
step lives in Streamlit session state, the completion in the flag file,
so closing the app mid-setup reopens where the friend left off.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

_FLAG_PATH = Path(__file__).resolve().parents[3] / "creds" / "setup_complete.flag"


def setup_complete() -> bool:
    """Whether first-run setup has been finished (or skipped)."""
    try:
        return _FLAG_PATH.is_file()
    except OSError:
        return False


def mark_setup_complete() -> None:
    """Record that setup is done — the wizard won't show again."""
    _FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FLAG_PATH.write_text(
        "First-run setup finished. Delete this file to run the wizard again.\n",
        encoding="utf-8",
    )


def reset_setup() -> None:
    """Remove the completion flag so the wizard runs again."""
    with contextlib.suppress(FileNotFoundError):
        _FLAG_PATH.unlink()


def setup_complete_flag_path() -> Path:
    """Path to the completion sentinel (for tests / the operator)."""
    return _FLAG_PATH
