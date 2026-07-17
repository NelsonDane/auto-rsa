"""Simple Mode hides advanced sections + the license-bypass toggle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["RSA_LICENSE_BYPASS"] = "1"

from streamlit.testing.v1 import AppTest

from src.gui.core import wizard
from src.gui.core.runner import TradeRunner
from src.gui.core.vault import Vault
from src.license import client as lic

APP = str(Path(__file__).resolve().parents[1] / "src/gui/app.py")


def _app(monkeypatch, *, simple: bool):
    monkeypatch.setenv("RSA_SIMPLE_MODE", "1" if simple else "0")
    # These tests exercise the normal UI, not the first-run wizard.
    monkeypatch.setattr(wizard, "setup_complete", lambda: True)
    # License tab (if rendered) must not hit the network.
    monkeypatch.setattr(
        lic, "killswitch_status",
        lambda: {"active": False, "message": "", "min_app_version": "", "reachable": True},
    )
    d = Path(tempfile.mkdtemp())
    v = Vault(d / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = v
    at.session_state["runner"] = TradeRunner(v)
    return at


def test_simple_mode_drops_advanced_section(monkeypatch):
    at = _app(monkeypatch, simple=True)
    # An advanced section that Simple Mode hides.
    at.session_state["active_section"] = "Signals"
    at.run()
    assert not at.exception, at.exception
    # "Signals" isn't in the Simple label set -> reset to the first (Status).
    assert at.session_state["active_section"] == "Status"


def test_full_mode_keeps_advanced_section(monkeypatch):
    at = _app(monkeypatch, simple=False)
    at.session_state["active_section"] = "Signals"
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["active_section"] == "Signals"


def test_simple_mode_hides_bypass_toggle(monkeypatch):
    at = _app(monkeypatch, simple=True)
    at.run()
    assert not at.exception, at.exception
    assert not any(
        "Disable license broker cap" in (c.label or "") for c in at.checkbox
    )


def test_full_mode_shows_bypass_toggle(monkeypatch):
    at = _app(monkeypatch, simple=False)
    at.run()
    assert not at.exception, at.exception
    assert any(
        "Disable license broker cap" in (c.label or "") for c in at.checkbox
    )


def test_credentials_curates_browser_brokers_in_simple(monkeypatch):
    at = _app(monkeypatch, simple=True)
    at.session_state["active_section"] = "Credentials"
    at.run()
    assert not at.exception, at.exception
    # Browser brokers sit behind the 'Advanced brokers' expander, whose
    # warning names their lack of an official API.
    assert any("no official API" in (w.value or "") for w in at.warning)


def test_credentials_uncurated_in_full_mode(monkeypatch):
    at = _app(monkeypatch, simple=False)
    at.session_state["active_section"] = "Credentials"
    at.run()
    assert not at.exception, at.exception
    assert not any("no official API" in (w.value or "") for w in at.warning)


def test_simple_mode_trade_tab_has_stuck_stock_reset(monkeypatch):
    # The Ledger tab is hidden in Simple Mode; the Trade tab must offer the
    # reset-by-ticker recovery so a blocked stock isn't a dead end.
    at = _app(monkeypatch, simple=True)
    at.session_state["active_section"] = "Trade"
    at.run()
    assert not at.exception, at.exception
    assert any("Reset this stock" in (b.label or "") for b in at.button)


def test_full_mode_trade_tab_has_no_simple_reset(monkeypatch):
    at = _app(monkeypatch, simple=False)
    at.session_state["active_section"] = "Trade"
    at.run()
    assert not at.exception, at.exception
    assert not any("Reset this stock" in (b.label or "") for b in at.button)


def test_simple_mode_trade_tab_hides_reset_while_running(monkeypatch):
    # REG-2: the reset-by-ticker control deletes ledger rows, so it must be
    # HIDDEN while a run is in progress (resetting a ticker mid-run would wipe
    # its in-flight row and re-open a double-buy). Simple Mode + running ->
    # no reset button (and the "run in progress" notice instead).
    at = _app(monkeypatch, simple=True)
    at.session_state["active_section"] = "Trade"
    runner = at.session_state["runner"]
    monkeypatch.setattr(runner, "is_running", lambda: True)
    at.run()
    assert not at.exception, at.exception
    assert not any("Reset this stock" in (b.label or "") for b in at.button)
    assert any("run is still in progress" in (i.value or "") for i in at.info)
