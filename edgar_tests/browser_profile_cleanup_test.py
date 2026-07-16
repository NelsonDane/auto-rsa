"""Unit tests for the scoped browser-profile cleanup helper.

``kill_stale_profile_browsers`` must kill ONLY Chrome/chromedriver whose
command line references BOTH the ``creds`` dir AND the broker's profile
marker — never the operator's own Chrome — then clear the singleton-lock
files so the profile reopens with its saved session intact. It must never
raise. These tests inject a fake ``psutil`` (the module imports it lazily)
so no real processes are touched.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from src.brokerages._browser_profile_cleanup import (
    _LOCK_FILES,
    kill_stale_profile_browsers,
)


class _FakeProc:
    def __init__(self, name: str, cmdline: list[str]) -> None:
        self.info = {"name": name, "cmdline": cmdline}
        self.killed = False
        self._kill_exc: Exception | None = None

    def kill(self) -> None:
        if self._kill_exc is not None:
            raise self._kill_exc
        self.killed = True


def _install_fake_psutil(monkeypatch, procs: list[_FakeProc]):
    """Register a minimal fake ``psutil`` for the duration of a test."""
    mod = types.ModuleType("psutil")

    class _Err(Exception):
        pass

    class _NoSuchProcess(_Err):
        pass

    class _AccessDenied(_Err):
        pass

    mod.Error = _Err  # type: ignore[attr-defined]
    mod.NoSuchProcess = _NoSuchProcess  # type: ignore[attr-defined]
    mod.AccessDenied = _AccessDenied  # type: ignore[attr-defined]
    mod.process_iter = lambda attrs=None: list(procs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psutil", mod)
    return mod


def test_kills_only_matching_profile_chrome(tmp_path, monkeypatch):
    """Only the WF zombie (creds path AND profile marker) is killed."""
    root = Path(str(tmp_path)).resolve()
    wf_zombie = _FakeProc(
        "chrome", ["/opt/chromium", f"--user-data-dir={root}/wellsfargo_profile"],
    )
    chase_zombie = _FakeProc(
        "chrome", ["/opt/chromium", f"--user-data-dir={root}/chase_1"],
    )
    # Operator's own Chrome that happens to browse a URL containing the
    # marker text but has NO creds path -> must survive (proves AND).
    operator_chrome = _FakeProc(
        "chrome", ["chrome", "https://example.com/wellsfargo_profile/x"],
    )
    # Non-browser process referencing the profile -> must survive.
    stray_python = _FakeProc(
        "python", ["python", f"{root}/wellsfargo_profile/log"],
    )
    procs = [wf_zombie, chase_zombie, operator_chrome, stray_python]
    _install_fake_psutil(monkeypatch, procs)

    killed = kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile")

    assert killed == 1
    assert wf_zombie.killed is True
    assert chase_zombie.killed is False
    assert operator_chrome.killed is False
    assert stray_python.killed is False


def test_kills_chromedriver_too(tmp_path, monkeypatch):
    root = Path(str(tmp_path)).resolve()
    driver = _FakeProc(
        "chromedriver", ["chromedriver", f"--user-data-dir={root}/wellsfargo_profile"],
    )
    _install_fake_psutil(monkeypatch, [driver])
    assert kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile") == 1
    assert driver.killed is True


def test_counts_multiple_zombies(tmp_path, monkeypatch):
    root = Path(str(tmp_path)).resolve()
    procs = [
        _FakeProc("chrome", [f"--user-data-dir={root}/wellsfargo_profile"]),
        _FakeProc("chrome", [f"--user-data-dir={root}/wellsfargo_profile", "--x"]),
    ]
    _install_fake_psutil(monkeypatch, procs)
    assert kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile") == 2


def test_clears_only_lock_files_keeps_session(tmp_path, monkeypatch):
    """The singleton locks go; cookies / the profile dir stay."""
    root = Path(str(tmp_path)).resolve()
    profile = root / "wellsfargo_profile"
    profile.mkdir(parents=True)
    for lock in _LOCK_FILES:
        (profile / lock).write_text("x", encoding="utf-8")
    cookies = profile / "Cookies"
    cookies.write_text("session", encoding="utf-8")

    _install_fake_psutil(monkeypatch, [])
    kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile")

    for lock in _LOCK_FILES:
        assert not (profile / lock).exists(), f"{lock} should be cleared"
    assert cookies.exists(), "saved session (Cookies) must be preserved"
    assert profile.is_dir(), "profile dir itself must be preserved"


def test_missing_lock_files_is_fine(tmp_path, monkeypatch):
    """No SingletonLock present -> no error, still returns cleanly."""
    root = Path(str(tmp_path)).resolve()
    (root / "wellsfargo_profile").mkdir(parents=True)
    _install_fake_psutil(monkeypatch, [])
    assert kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile") == 0


def test_no_psutil_returns_zero_without_touching_locks(tmp_path, monkeypatch):
    """If psutil can't be imported the helper degrades to a no-op."""
    root = Path(str(tmp_path)).resolve()
    profile = root / "wellsfargo_profile"
    profile.mkdir(parents=True)
    lock = profile / "SingletonLock"
    lock.write_text("x", encoding="utf-8")
    # Force `import psutil` to raise ImportError.
    monkeypatch.setitem(sys.modules, "psutil", None)

    assert kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile") == 0
    # Early return -> lock untouched (we never claim to have cleaned up).
    assert lock.exists()


def test_kill_race_is_swallowed(tmp_path, monkeypatch):
    """A proc that dies between iteration and kill must not abort the sweep."""
    root = Path(str(tmp_path)).resolve()
    racy = _FakeProc("chrome", [f"--user-data-dir={root}/wellsfargo_profile"])
    good = _FakeProc("chrome", [f"--user-data-dir={root}/wellsfargo_profile", "--b"])
    _install_fake_psutil(monkeypatch, [racy, good])
    racy._kill_exc = sys.modules["psutil"].NoSuchProcess()  # type: ignore[attr-defined]

    killed = kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile")
    # racy raised (not counted); good still killed -> sweep continued.
    assert killed == 1
    assert good.killed is True


def test_handles_none_cmdline(tmp_path, monkeypatch):
    """psutil may hand back cmdline=None for a dead proc -> no crash."""
    none_proc = _FakeProc("chrome", None)  # type: ignore[arg-type]
    none_name = _FakeProc(None, ["chrome"])  # type: ignore[arg-type]
    _install_fake_psutil(monkeypatch, [none_proc, none_name])
    assert kill_stale_profile_browsers(str(tmp_path), "wellsfargo_profile") == 0
    assert none_proc.killed is False
