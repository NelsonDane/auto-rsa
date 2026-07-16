"""Tests for the LIVE-run pre-flight heads-up."""

from __future__ import annotations

from src import session_state
from src.gui.core import diagnostics, preflight


def test_expired_session_warns_only_for_selected_brokers(monkeypatch):
    # fidelity RED (expired), bbae GREEN, chase RED — but only select
    # fidelity + bbae, so only fidelity should warn.
    snap = [
        {"broker": "fidelity", "health": session_state.RED},
        {"broker": "bbae", "health": session_state.GREEN},
        {"broker": "chase", "health": session_state.RED},
    ]
    monkeypatch.setattr(session_state, "load_last_audit", lambda: snap)
    monkeypatch.setattr(diagnostics, "inspect_run_lock", lambda: None)

    items = preflight.preflight_for_run(["fidelity", "bbae"])
    msgs = " ".join(i.message for i in items)
    assert "fidelity" in msgs
    assert "bbae" not in msgs
    assert "chase" not in msgs  # not selected
    assert all(i.level == preflight.WARN for i in items)


def test_all_green_no_warnings(monkeypatch):
    monkeypatch.setattr(
        session_state, "load_last_audit",
        lambda: [{"broker": "bbae", "health": session_state.GREEN}],
    )
    monkeypatch.setattr(diagnostics, "inspect_run_lock", lambda: None)
    assert preflight.preflight_for_run(["bbae"]) == []


def test_stale_lock_warns(monkeypatch):
    monkeypatch.setattr(session_state, "load_last_audit", lambda: [])
    monkeypatch.setattr(session_state, "audit", lambda **_k: [])
    monkeypatch.setattr(
        diagnostics, "inspect_run_lock", lambda: {"stale": True},
    )
    items = preflight.preflight_for_run(["bbae"])
    assert any("stale run lock" in i.message for i in items)


def test_never_raises_when_audit_blows_up(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(session_state, "load_last_audit", _boom)
    monkeypatch.setattr(session_state, "audit", _boom)
    monkeypatch.setattr(diagnostics, "inspect_run_lock", _boom)
    # Must not raise — returns whatever it could gather (here nothing).
    assert preflight.preflight_for_run(["bbae"]) == []
