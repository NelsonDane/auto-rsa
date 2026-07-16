"""System health checks + troubleshooting helpers for the GUI.

Everything here is best-effort and read-only unless a function name says
otherwise (only :func:`force_release_run_lock` mutates state, and only a
stale/abandoned lock). Nothing raises: a check that can't run reports a
WARN/FAIL row rather than blowing up the page it's rendered on.

The point is to make *silent* problems loud: a missing broker dependency
that makes every engine run die at import (the run just "doesn't work"),
a stale run lock that blocks every new run, a full disk that fails the
audit-log write, an expired broker session that needs a manual re-login.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import shutil
import subprocess  # noqa: S404
import sys
from pathlib import Path
from typing import NamedTuple

import psutil

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CREDS = _PROJECT_ROOT / "creds"
_RUN_LOCK = _CREDS / "run.lock"
_RUN_LOGS = _CREDS / "run_logs"

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_ICON = {OK: "🟢", WARN: "🟡", FAIL: "🔴"}

# Warn when the volume backing creds/ has less than this much free space —
# an engine run writes an audit log and brokers write session artifacts,
# and a full disk fails those writes silently.
_LOW_DISK_MB = 200
_MIN_PY = (3, 11)


class HealthCheck(NamedTuple):
    """One diagnostic row."""

    name: str
    status: str  # OK | WARN | FAIL
    detail: str

    @property
    def icon(self) -> str:
        """Traffic-light emoji for this row's status."""
        return _ICON.get(self.status, "❔")


def _lock_info() -> dict | None:
    try:
        return json.loads(_RUN_LOCK.read_text())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: object) -> bool:
    with contextlib.suppress(Exception):
        return pid is not None and psutil.pid_exists(int(pid))
    return False


def inspect_run_lock() -> dict | None:
    """Return details about the single-run lock, or None if not held.

    Keys: ``engine_pid``, ``owner_pid``, ``created`` (epoch), ``age_s``,
    ``engine_alive``, ``owner_alive``, ``stale`` (nothing keeping it
    alive -> a new run is being blocked for no reason).
    """
    info = _lock_info()
    if info is None:
        return None
    engine_pid = info.get("engine_pid")
    owner_pid = info.get("owner_pid")
    created = float(info.get("created", 0) or 0)
    engine_alive = _pid_alive(engine_pid)
    owner_alive = _pid_alive(owner_pid)
    # Stale = neither the engine nor the GUI that took the lock is alive.
    # (If no pids were recorded we can't prove staleness here; treat as
    # not-stale so we never yank a lock a live run still needs.)
    known = engine_pid is not None or owner_pid is not None
    stale = known and not engine_alive and not owner_alive
    return {
        "engine_pid": engine_pid,
        "owner_pid": owner_pid,
        "created": created,
        "engine_alive": engine_alive,
        "owner_alive": owner_alive,
        "stale": stale,
    }


def force_release_run_lock() -> bool:
    """Delete the run-lock file. Returns True if a lock was removed.

    Recovery action for a stale/abandoned lock that blocks every new
    run. The caller is responsible for confirming the lock is actually
    stale (see :func:`inspect_run_lock`) before offering this.
    """
    try:
        _RUN_LOCK.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def list_run_logs(limit: int = 40) -> list[dict]:
    """Recent engine-run audit logs, newest first.

    Each entry: ``name``, ``path`` (str), ``when`` (datetime|None),
    ``status`` (finished/error/cancelled parsed from the filename),
    ``size`` (bytes). Files are ``creds/run_logs/<stamp>_<status>.log``.
    """
    if not _RUN_LOGS.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(_RUN_LOGS.glob("*.log"), reverse=True)[:limit]:
        stem = p.stem  # e.g. 20260710T204312Z_error
        stamp, _, status = stem.partition("_")
        when = None
        with contextlib.suppress(ValueError):
            when = datetime.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=datetime.UTC,
            )
        size = 0
        with contextlib.suppress(OSError):
            size = p.stat().st_size
        out.append(
            {
                "name": p.name,
                "path": str(p),
                "when": when,
                "status": status or "unknown",
                "size": size,
            },
        )
    return out


def read_run_log(path: str, *, tail: int | None = None) -> str:
    """Read an audit log; if ``tail`` is set, only its last N lines."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read log: {exc})"
    if tail is not None:
        lines = text.splitlines()
        if len(lines) > tail:
            omitted = len(lines) - tail
            return f"… ({omitted} earlier lines omitted) …\n" + "\n".join(
                lines[-tail:],
            )
    return text


def check_engine_importable(timeout: float = 90.0) -> HealthCheck:
    """Import the engine in a subprocess exactly as a run would.

    This is the check that catches the most damaging *silent* failure:
    a missing broker dependency (e.g. ``selenium_stealth``) makes the
    engine subprocess die at ``import src.auto_rsa`` on every run, so
    the run "just doesn't work" with nothing actionable on screen. Doing
    it out-of-process avoids importing heavy broker libs into the GUI
    and mirrors what the engine actually does at startup.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-c", "import src.auto_rsa"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HealthCheck(
            "Engine import",
            WARN,
            f"import did not finish within {timeout:.0f}s — the engine may "
            "be slow to start, or a broker library is hanging at import.",
        )
    except Exception as exc:  # noqa: BLE001
        return HealthCheck("Engine import", WARN, f"could not run check: {exc}")
    if proc.returncode == 0:
        return HealthCheck(
            "Engine import", OK, "src.auto_rsa imports cleanly (engine can start).",
        )
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    last = err[-1] if err else "unknown import error"
    return HealthCheck(
        "Engine import",
        FAIL,
        f"the engine fails to import — every run will die at startup: {last}",
    )


def quick_health_checks(*, vault_initialized: bool, vault_unlocked: bool) -> list[HealthCheck]:
    """Instant, side-effect-free checks (no engine import — that's slow).

    ``vault_initialized`` / ``vault_unlocked`` are passed in so this
    module stays decoupled from the GUI's Vault instance.
    """
    checks: list[HealthCheck] = []

    # Python version.
    v = sys.version_info
    py = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= _MIN_PY:
        checks.append(HealthCheck("Python", OK, f"{py}"))
    else:
        checks.append(
            HealthCheck(
                "Python", WARN,
                f"{py} — project targets {_MIN_PY[0]}.{_MIN_PY[1]}+",
            ),
        )

    # Vault.
    if not vault_initialized:
        checks.append(
            HealthCheck("Vault", WARN, "no vault yet — set a master password first."),
        )
    elif vault_unlocked:
        checks.append(HealthCheck("Vault", OK, "initialized and unlocked."))
    else:
        checks.append(
            HealthCheck("Vault", WARN, "locked — unlock it in the sidebar to run."),
        )

    # creds/ writable (audit logs + session artifacts live here).
    checks.append(_check_creds_writable())

    # Disk space on the volume backing creds/.
    checks.append(_check_disk())

    # Run lock.
    checks.append(_check_run_lock())

    return checks


def _check_creds_writable() -> HealthCheck:
    try:
        _CREDS.mkdir(parents=True, exist_ok=True)
        probe = _CREDS / ".diag_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return HealthCheck(
            "creds/ writable", FAIL,
            f"cannot write to {_CREDS} — runs can't save logs/sessions: {exc}",
        )
    return HealthCheck("creds/ writable", OK, f"{_CREDS} is writable.")


def _check_disk() -> HealthCheck:
    try:
        usage = shutil.disk_usage(_CREDS if _CREDS.exists() else _PROJECT_ROOT)
    except OSError as exc:
        return HealthCheck("Disk space", WARN, f"could not check: {exc}")
    free_mb = usage.free / (1024 * 1024)
    if free_mb < _LOW_DISK_MB:
        return HealthCheck(
            "Disk space", WARN,
            f"only {free_mb:.0f} MB free — writes (audit logs, sessions) may fail.",
        )
    return HealthCheck("Disk space", OK, f"{free_mb / 1024:.1f} GB free.")


def _check_run_lock() -> HealthCheck:
    lock = inspect_run_lock()
    if lock is None:
        return HealthCheck("Run lock", OK, "free — a new run can start.")
    if lock["stale"]:
        return HealthCheck(
            "Run lock", FAIL,
            "held by a process that is no longer alive — this blocks every "
            "new run. Use 'Clear stuck run' below to release it.",
        )
    who = "engine" if lock["engine_alive"] else "GUI"
    return HealthCheck(
        "Run lock", WARN,
        f"held by a live {who} process — a run is in progress (or a browser "
        "tab is mid-run). Normal if you're running now.",
    )
