"""Re-run only the brokers that failed."""

from __future__ import annotations

import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.gui.core import runner as runner_mod
from src.gui.core.runner import RunStatus, TradeRunner
from src.gui.core.vault import Vault

APP = str((Path(__file__).resolve().parents[1] / "src/gui/app.py"))


def _runner(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    return TradeRunner(v)


def test_last_spec_round_trips(tmp_path, monkeypatch):
    r = _runner(tmp_path, monkeypatch)
    assert r.last_spec() is None
    r._last_spec = {"kind": "holdings"}
    got = r.last_spec()
    assert got == {"kind": "holdings"}
    got["mutated"] = True  # must be a copy, not the internal dict
    assert "mutated" not in r._last_spec


def _seed_failed_runner(tmp_path, monkeypatch, spec):
    r = _runner(tmp_path, monkeypatch)
    r._status = RunStatus.FINISHED
    r._progress = {"bbae": "failed", "fennel": "done"}
    r._last_spec = spec
    return r


def test_retry_banner_shows_for_failed_brokers(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        r = _seed_failed_runner(Path(d), monkeypatch, {"kind": "holdings"})
        v = r._vault
        at = AppTest.from_file(APP, default_timeout=45)
        at.session_state["vault"] = v
        at.session_state["runner"] = r
        at.run()
        assert not at.exception, at.exception
        labels = [b.label for b in at.button]
        assert any("Re-run the 1 failed broker" in b for b in labels), labels


def test_retry_dry_starts_failed_only_directly(monkeypatch):
    """A dry/holdings re-run needs no confirmation — one click starts it,
    scoped to just the failed broker."""
    with tempfile.TemporaryDirectory() as d:
        r = _seed_failed_runner(Path(d), monkeypatch, {"kind": "holdings"})
        calls = []
        r.start_holdings = lambda bks: calls.append(list(bks))  # type: ignore[method-assign]
        at = AppTest.from_file(APP, default_timeout=45)
        at.session_state["vault"] = r._vault
        at.session_state["runner"] = r
        at.run()
        [b for b in at.button if "Re-run the 1 failed" in (b.label or "")][0].click()
        at.run()
        assert not at.exception, at.exception
        assert calls == [["bbae"]]


def test_retry_live_requires_execute_then_fires(monkeypatch):
    """A LIVE re-run uses the same same-page gate: an unconfirmed click is
    blocked; typing EXECUTE and clicking fires it, scoped to the failed
    broker only."""
    spec = {
        "kind": "trade", "action": "buy", "amount": 1.0, "tickers": ["VIVK"],
        "price_type": "market", "time_in_force": "day", "limit_price": None,
        "dry": False, "parallel": False, "parallel_cap": 0,
    }
    with tempfile.TemporaryDirectory() as d:
        r = _seed_failed_runner(Path(d), monkeypatch, spec)
        calls = {}
        r.start_trade = lambda *a, **k: calls.update(args=a, kwargs=k)  # type: ignore[method-assign]
        at = AppTest.from_file(APP, default_timeout=45)
        at.session_state["vault"] = r._vault
        at.session_state["runner"] = r
        at.run()
        live_btn = [
            b for b in at.button if "Re-run 1 failed broker(s) LIVE" in (b.label or "")
        ][0]
        # Unconfirmed click -> blocked, nothing started.
        live_btn.click()
        at.run()
        assert not calls, "unconfirmed LIVE re-run must not start"
        assert any("NOT started" in (e.value or "") for e in at.error)
        # Type EXECUTE, click -> fires, failed broker only.
        at.text_input(key="retry_arm").set_value("EXECUTE")
        [b for b in at.button if "Re-run 1 failed broker(s) LIVE" in (b.label or "")][0].click()
        at.run()
        assert not at.exception, at.exception
        assert calls["args"][3] == ["bbae"]  # broker_keys arg
        assert calls["kwargs"]["dry"] is False
