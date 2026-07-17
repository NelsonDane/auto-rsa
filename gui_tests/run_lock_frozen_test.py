"""Run-lock liveness must recognize the frozen engine cmdline.

Regression for the double-submit: in a Nuitka build the engine's OS
cmdline is `AutoRSA.exe --engine <json>` (no "engine_proc"). If
_engine_pid_state misreads that live engine as "other", _lock_is_stale
reclaims the lock mid-run and a second tab can start a concurrent LIVE
run.
"""

import os

os.environ.setdefault("RSA_LICENSE_BYPASS", "1")

from src.gui.core import runner


class _FakeProc:
    def __init__(self, argv):
        self._argv = argv

    def cmdline(self):
        return self._argv


def _state(monkeypatch, argv):
    monkeypatch.setattr(runner.psutil, "Process", lambda _pid: _FakeProc(argv))
    return runner.TradeRunner._engine_pid_state(4321)


def test_source_engine_is_live(monkeypatch):
    argv = ["/usr/bin/python", "-u", "-m", "src.gui.core.engine_proc", "{}"]
    assert _state(monkeypatch, argv) == "engine"


def test_frozen_engine_is_live(monkeypatch):
    argv = [r"C:\Users\me\AutoRSA\AutoRSA.exe", "--engine", '{"args": []}']
    assert _state(monkeypatch, argv) == "engine"


def test_unrelated_process_is_other(monkeypatch):
    argv = [r"C:\Windows\notepad.exe"]
    assert _state(monkeypatch, argv) == "other"


def test_dead_process(monkeypatch):
    def _raise(_pid):
        raise runner.psutil.NoSuchProcess(_pid)

    monkeypatch.setattr(runner.psutil, "Process", _raise)
    assert runner.TradeRunner._engine_pid_state(4321) == "dead"
