"""Trade Beta tab: parallel flag flows from UI -> runner payload."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["RSA_LICENSE_BYPASS"] = "1"  # allow >1 broker in the test vault

from streamlit.testing.v1 import AppTest

from src.gui.core import runner as runner_mod
from src.gui.core.runner import TradeRunner
from src.gui.core.vault import Vault

APP = str(Path(__file__).resolve().parents[1] / "src/gui/app.py")


def _btn(at, label):
    """Find a (form submit) button by exact label."""
    hits = [b for b in at.button if (b.label or "") == label]
    assert hits, f"button {label!r} not found in {[b.label for b in at.button]}"
    return hits[0]


def test_start_trade_records_parallel(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    captured = {}
    monkeypatch.setattr(
        r, "_start",
        lambda payload, *a, **k: captured.update(payload=payload),
    )
    r.start_trade(
        "buy", 1.0, ["VIVK"], ["bbae"], dry=True,
        parallel=True, parallel_cap=4,
    )
    assert captured["payload"]["parallel"] is True
    assert captured["payload"]["parallel_cap"] == 4
    assert r.last_spec()["parallel"] is True
    assert r.last_spec()["parallel_cap"] == 4

    # Default (Trade tab) path leaves parallel off.
    r.start_trade("buy", 1.0, ["VIVK"], ["bbae"], dry=True)
    assert captured["payload"]["parallel"] is False


def _vault():
    d = Path(tempfile.mkdtemp())
    v = Vault(d / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    v.set_broker("dspac", [{"username": "u2", "password": "p2"}])
    return v


def test_beta_tab_renders():
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = _vault()
    at.run()
    assert not at.exception, at.exception
    assert any("Parallel (Beta)" in (m.value or "") for m in at.subheader) or any(
        "Parallel" in (m.value or "") for m in at.markdown
    )


def test_beta_live_unconfirmed_click_is_blocked(monkeypatch):
    """Clicking LIVE without EXECUTE typed must not place anything —
    checked server-side on the atomic form submit."""
    at = AppTest.from_file(APP, default_timeout=45)
    v = _vault()
    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.run()
    at.text_input(key="beta_tickers").set_value("VIVK")
    _btn(at, "🔴 Execute LIVE order (parallel)").click()
    at.run()
    assert not at.exception, at.exception
    assert not calls, "unconfirmed LIVE click must not start a trade"
    assert any(
        "type EXECUTE in the confirmation" in (e.value or "") for e in at.error
    )


def test_beta_live_confirmed_fires_in_one_submit(monkeypatch):
    """The atomic form: ticker + EXECUTE text + LIVE click delivered in
    ONE submit — the trade starts in that same run. This is the fix for
    'I typed EXECUTE but the button never triggered the workflow': no
    intermediate widget sync is needed anymore."""
    at = AppTest.from_file(APP, default_timeout=45)
    v = _vault()
    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.run()
    # Set everything and click in ONE submit — no intermediate at.run().
    at.text_input(key="beta_tickers").set_value("VIVK")
    at.text_input(key="beta_arm").set_value("execute")  # case-insensitive
    _btn(at, "🔴 Execute LIVE order (parallel)").click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["dry"] is False
    assert calls["kwargs"]["parallel"] is True
    assert calls["kwargs"]["parallel_cap"] == 6  # slider default
    assert calls["args"][2] == ["VIVK"]
    # Confirmation clears after a successful LIVE start.
    assert at.session_state["beta_arm"] == ""


def test_trade_tab_live_confirmed_fires_in_one_submit(monkeypatch):
    """The plain Trade tab uses the same atomic form (sequential)."""
    at = AppTest.from_file(APP, default_timeout=45)
    v = _vault()
    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.run()
    at.text_input(key="trade_tickers").set_value("CIIT")
    at.text_input(key="trade_arm").set_value("EXECUTE")
    _btn(at, "🔴 Execute LIVE order").click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["dry"] is False
    assert not calls["kwargs"].get("parallel")
    assert calls["args"][2] == ["CIIT"]
    assert at.session_state["trade_arm"] == ""  # cleared after firing


def test_trade_fires_with_actionable_signals_loaded(monkeypatch):
    """Regression: with actionable signals loaded, the Signals tab AND the
    Trade tab both render the sub-account filter every rerun. When they
    shared a fixed st.form key, the second one threw during render —
    BEFORE the Trade submit handler ran — so a live trade (a sell in the
    field report) silently did nothing. Per-tab form keys must keep both
    forms alive AND let the Trade submit reach start_trade."""
    import types

    from src.gui import app as app_mod
    from src.gui.core import signal_plan as sp_mod
    from src.gui.core.sheets import Signal

    d = Path(tempfile.mkdtemp())
    v = Vault(d / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    v.set_sheets_config('{"x": 1}', "sheet123", "GUI_QUEUE")
    sig = Signal(
        created_at="", ticker="FOMO", action="buy", ratio="1-40",
        effective_date="2099-01-01", presplit_deadline="", fractional_policy="",
        confidence="0.9", source="", key="SIG:1", status="",
    )
    item = types.SimpleNamespace(
        decision=app_mod.DECISION_ACTIONABLE, ticker="FOMO", ratio="1-40",
        effective_date="2099-01-01", confidence=0.9, key="SIG:1",
        split_key="X", fractional_policy="ROUND_UP", reason="",
    )
    monkeypatch.setattr(sp_mod, "plan_signals", lambda *a, **k: [item])
    monkeypatch.setattr(app_mod, "plan_signals", lambda *a, **k: [item])

    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.session_state["signals"] = [sig]
    at.run()
    assert not at.exception, at.exception  # no duplicate-form crash

    at.selectbox(key="trade_action").set_value("sell")
    at.text_input(key="trade_tickers").set_value("QNCX")
    at.text_input(key="trade_arm").set_value("EXECUTE")
    _btn(at, "🔴 Execute LIVE order").click()
    at.run()
    assert not at.exception, at.exception
    assert calls, "the sell must reach start_trade even with signals loaded"
    assert calls["args"][0] == "sell"
    assert calls["kwargs"]["dry"] is False


def test_clear_brokers_button(monkeypatch):
    """The clear-brokers button empties the selection so a fresh set can
    be picked."""
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = _vault()
    at.run()
    # Default = all configured selected.
    assert "trade_sel" in at.session_state
    assert at.session_state["trade_sel"], "brokers selected by default"
    [b for b in at.button if "Clear brokers" in (b.label or "")][0].click()
    at.run()
    assert at.session_state["trade_sel"] == []


def test_activity_panel_has_manual_refresh():
    """The activity panel must always expose a manual refresh button so the
    operator can pull the latest run status/log on demand even when the 2s
    auto-poll is unreliable on their browser/OS (the 'sits on (no output
    yet) while the engine is actually running' failure)."""
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = _vault()
    at.run()
    assert not at.exception, at.exception
    assert any(
        "Refresh status" in (b.label or "") for b in at.button
    ), "activity panel must expose a manual '🔄 Refresh status' button"


def test_beta_dry_button_starts_parallel(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = _vault()
    # Inject a runner whose start_trade we can observe.
    r = TradeRunner(at.session_state["vault"])
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["runner"] = r
    at.run()
    at.text_input(key="beta_tickers").set_value("VIVK")
    _btn(at, "▶ Execute dry run (parallel)").click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["parallel"] is True
    assert calls["kwargs"]["dry"] is True
    assert calls["kwargs"]["parallel_cap"] == 6
