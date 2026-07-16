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


def test_beta_live_unarmed_click_is_blocked(monkeypatch):
    """Server-side guard: clicking LIVE without typing EXECUTE must not
    place anything (the disabled flag is only a frontend hint)."""
    at = AppTest.from_file(APP, default_timeout=45)
    v = _vault()
    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.run()
    at.text_input(key="beta_tickers").set_value("VIVK")
    at.run()
    at.button(key="beta_go_live").click()
    at.run()
    assert not at.exception, at.exception
    assert not calls, "unarmed LIVE click must not start a trade"
    assert any("arm the LIVE button" in (e.value or "") for e in at.error)


def test_beta_live_armed_fires_same_page_parallel(monkeypatch):
    """Same-page gate: type EXECUTE to arm, then the LIVE click itself
    starts the parallel trade — no separate confirm screen, no rerun
    handoff (the failure mode that blocked live trading)."""
    at = AppTest.from_file(APP, default_timeout=45)
    v = _vault()
    r = TradeRunner(v)
    calls = {}
    r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
    at.session_state["vault"] = v
    at.session_state["runner"] = r
    at.run()
    at.text_input(key="beta_tickers").set_value("VIVK")
    at.text_input(key="beta_arm").set_value("execute")  # case-insensitive
    at.run()
    at.button(key="beta_go_live").click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["dry"] is False
    assert calls["kwargs"]["parallel"] is True
    assert calls["kwargs"]["parallel_cap"] == 6  # slider default
    assert calls["args"][2] == ["VIVK"]
    # Gate disarms after a successful LIVE start.
    assert at.session_state["beta_arm"] == ""


def test_trade_tab_live_armed_fires_same_page(monkeypatch):
    """The plain Trade tab uses the same same-page gate (sequential)."""
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
    at.run()
    live = [b for b in at.button if (b.label or "") == "🔴 Execute LIVE order"]
    assert live, [b.label for b in at.button]
    live[0].click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["dry"] is False
    assert "parallel" not in calls["kwargs"] or not calls["kwargs"]["parallel"]
    assert calls["args"][2] == ["CIIT"]
    assert at.session_state["trade_arm"] == ""  # disarmed after firing


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
    at.run()
    at.button(key="beta_go_dry").click()
    at.run()
    assert not at.exception, at.exception
    assert calls["kwargs"]["parallel"] is True
    assert calls["kwargs"]["dry"] is True
    assert calls["kwargs"]["parallel_cap"] == 6
