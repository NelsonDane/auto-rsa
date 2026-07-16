"""Per-broker run timeline + stuck-broker elapsed timing."""

from __future__ import annotations

from src.gui.core import runner as runner_mod
from src.gui.core.runner import STUCK_BROKER_SECONDS, RunStatus, TradeRunner
from src.gui.core.vault import Vault


def _mk(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    r._status = RunStatus.RUNNING
    return r


def _timings(r):
    return {b: (s, e) for b, s, e in r.snapshot().timings}


def test_timeline_tracks_running_broker(tmp_path, monkeypatch):
    r = _mk(tmp_path, monkeypatch)
    r._apply_progress("PLAN", "fidelity,bbae")
    r._apply_progress("START", "fidelity")
    t = _timings(r)
    assert t["fidelity"][0] == "running"
    assert t["fidelity"][1] >= 0
    # bbae hasn't started -> no timing row yet.
    assert "bbae" not in t


def test_running_broker_elapsed_grows_and_flags_stuck(tmp_path, monkeypatch):
    r = _mk(tmp_path, monkeypatch)
    r._apply_progress("PLAN", "fidelity")
    r._apply_progress("START", "fidelity")
    # Backdate the start to simulate a long-running (stuck) broker.
    r._broker_timings["fidelity"]["start"] -= STUCK_BROKER_SECONDS + 10
    state, elapsed = _timings(r)["fidelity"]
    assert state == "running"
    assert elapsed >= STUCK_BROKER_SECONDS  # the app renders the stuck hint


def test_elapsed_freezes_on_done(tmp_path, monkeypatch):
    r = _mk(tmp_path, monkeypatch)
    r._apply_progress("PLAN", "bbae")
    r._apply_progress("START", "bbae")
    r._broker_timings["bbae"]["start"] -= 5
    r._apply_progress("DONE", "bbae")
    e1 = _timings(r)["bbae"][1]
    # A later snapshot must not keep growing the elapsed for a finished broker.
    e2 = _timings(r)["bbae"][1]
    assert e1 == e2
    assert e1 >= 5


def test_plan_resets_timings(tmp_path, monkeypatch):
    r = _mk(tmp_path, monkeypatch)
    r._apply_progress("PLAN", "bbae")
    r._apply_progress("START", "bbae")
    assert "bbae" in _timings(r)
    # A new run's PLAN clears the prior run's timeline.
    r._apply_progress("PLAN", "fidelity")
    assert _timings(r) == {}
