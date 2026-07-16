"""Hang diagnostics for the GUI render loop.

Field symptom this exists for: the page's "Stop" indicator stays on and
content below some point renders dim/stale — i.e. a script run STARTED but
never FINISHED, so clicks appear dead and later tabs show stale output
(e.g. Balances stuck on a pre-unlock "vault locked" warning while the
sidebar says unlocked). That means some call in the render path is
blocking forever on the operator's machine — but WHICH call is machine-
specific, so instead of guessing, capture it:

* :func:`mark` — a render trace. main() marks each section as it starts;
  the file is truncated at the start of every run, so after a hang the
  LAST line names the section that never finished.
* :func:`arm` / :func:`disarm` — a faulthandler watchdog. If a run takes
  longer than the timeout, CPython dumps EVERY thread's stack (exact
  file:line of the frozen call) to the hang log, repeating until the run
  completes. Armed at the start of main(), disarmed at the end.

Both files live under creds/ (gitignored) and are shown in the
Diagnostics tab for copy/paste. Everything is best-effort: diagnostics
must never take the app down.
"""

from __future__ import annotations

import contextlib
import datetime
import faulthandler
from pathlib import Path

_CREDS = Path(__file__).resolve().parents[3] / "creds"
TRACE_PATH = _CREDS / "gui_render_trace.log"
HANG_DUMP_PATH = _CREDS / "gui_hang_dump.log"

# faulthandler needs the file object to stay alive for as long as the
# timer is armed — keep a module-global handle.
_hang_file = None

# Renders slower than this are considered hung and get stack-dumped.
# Generous enough that a legitimate slow section (vault scrypt unlock,
# a sheets fetch behind a spinner) doesn't false-positive constantly —
# and a false dump is harmless noise in a log file, never a crash.
HANG_TIMEOUT_S = 20.0


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S.%f")[:-3]


def begin_run() -> None:
    """Start a fresh trace for this script run (truncates the file)."""
    with contextlib.suppress(Exception):
        _CREDS.mkdir(parents=True, exist_ok=True)
        TRACE_PATH.write_text(f"{_now()} RUN START\n", encoding="utf-8")


def mark(section: str) -> None:
    """Append one section marker. The last marker in the file after a
    hang IS the section that never completed."""
    with contextlib.suppress(Exception):
        with TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {section}\n")


def end_run() -> None:
    with contextlib.suppress(Exception):
        with TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()} RUN COMPLETE\n")


def arm() -> None:
    """Arm (or re-arm) the hang watchdog for this run."""
    global _hang_file  # noqa: PLW0603
    with contextlib.suppress(Exception):
        _CREDS.mkdir(parents=True, exist_ok=True)
        if _hang_file is None or _hang_file.closed:
            _hang_file = HANG_DUMP_PATH.open("a", encoding="utf-8")
        _hang_file.write(f"\n--- watchdog armed {_now()} ---\n")
        _hang_file.flush()
        faulthandler.dump_traceback_later(
            HANG_TIMEOUT_S, repeat=True, file=_hang_file,
        )


def disarm() -> None:
    """Run finished in time — cancel the pending stack dump."""
    with contextlib.suppress(Exception):
        faulthandler.cancel_dump_traceback_later()


def read_trace() -> str:
    with contextlib.suppress(Exception):
        return TRACE_PATH.read_text(encoding="utf-8")
    return ""


def read_hang_dump(max_chars: int = 20000) -> str:
    with contextlib.suppress(Exception):
        text = HANG_DUMP_PATH.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]
    return ""


def last_run_completed() -> bool | None:
    """True/False whether the previous run finished; None if no trace."""
    trace = read_trace()
    if not trace.strip():
        return None
    return "RUN COMPLETE" in trace


def clear_hang_dump() -> None:
    global _hang_file  # noqa: PLW0603
    with contextlib.suppress(Exception):
        if _hang_file is not None and not _hang_file.closed:
            _hang_file.close()
        _hang_file = None
        HANG_DUMP_PATH.unlink(missing_ok=True)
