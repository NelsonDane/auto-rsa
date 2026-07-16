"""Signals tab: LIVE 1-share buy uses the same atomic same-page gate."""

from __future__ import annotations

import os
import tempfile
import types
from pathlib import Path

os.environ["RSA_LICENSE_BYPASS"] = "1"

from streamlit.testing.v1 import AppTest

from src.gui import app as app_mod
from src.gui.core.runner import TradeRunner
from src.gui.core.sheets import Signal
from src.gui.core.vault import Vault
from src.gui.core import signal_plan as sp_mod

APP = str(Path(__file__).resolve().parents[1] / "src/gui/app.py")


def _setup(monkeypatch):
    d = Path(tempfile.mkdtemp())
    v = Vault(d / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    # Sheet config so the Signals tab doesn't early-return.
    v.set_sheets_config('{"x": 1}', "sheet123", "GUI_QUEUE")

    sig = Signal(
        created_at="", ticker="FOMO", action="buy", ratio="1-40",
        effective_date="2099-01-01", presplit_deadline="", fractional_policy="",
        confidence="0.9", source="", key="SIG:1", status="",
    )
    item = types.SimpleNamespace(
        decision=app_mod.DECISION_ACTIONABLE, ticker="FOMO", ratio="1-40",
        effective_date="2099-01-01", confidence=0.9, key="SIG:1",
        split_key="FOMO|1-40|X", fractional_policy="ROUND_UP", reason="",
    )
    # Patch on BOTH the source module and app's bound name — AppTest may
    # reuse app's already-imported reference rather than re-binding.
    monkeypatch.setattr(sp_mod, "plan_signals", lambda *a, **k: [item])
    monkeypatch.setattr(app_mod, "plan_signals", lambda *a, **k: [item])

    r = TradeRunner(v)
    calls = {}
    r.start_signal_run = lambda **k: calls.update(k)  # type: ignore[method-assign]

    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.session_state["signals"] = [sig]
    return at, calls


def test_signal_live_unconfirmed_blocked(monkeypatch):
    at, calls = _setup(monkeypatch)
    at.run()
    assert not at.exception, at.exception
    live = [b for b in at.button if "Execute play LIVE" in (b.label or "")]
    assert live, [b.label for b in at.button]
    live[0].click()
    at.run()
    assert not calls, "unconfirmed LIVE signal must not start"
    assert any("LIVE buy NOT started" in (e.value or "") for e in at.error)


def test_signal_live_confirmed_fires(monkeypatch):
    at, calls = _setup(monkeypatch)
    at.run()
    at.text_input(key="signal_arm").set_value("execute")
    [b for b in at.button if "Execute play LIVE" in (b.label or "")][0].click()
    at.run()
    assert not at.exception, at.exception
    assert calls["dry"] is False
    assert calls["ticker"] == "FOMO"
    assert calls["broker_keys"] == ["all"]
    assert at.session_state["signal_arm"] == ""  # disarmed


def test_signal_dry_needs_no_confirmation(monkeypatch):
    at, calls = _setup(monkeypatch)
    at.run()
    [b for b in at.button if "Execute play (dry run)" in (b.label or "")][0].click()
    at.run()
    assert not at.exception, at.exception
    assert calls["dry"] is True
