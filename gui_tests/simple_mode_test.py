"""Simple Mode hides advanced sections + the license-bypass toggle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["RSA_LICENSE_BYPASS"] = "1"

from streamlit.testing.v1 import AppTest

from src.gui.core.runner import TradeRunner
from src.gui.core.vault import Vault
from src.license import client as lic

APP = str(Path(__file__).resolve().parents[1] / "src/gui/app.py")


def _app(monkeypatch, *, simple: bool):
    monkeypatch.setenv("RSA_SIMPLE_MODE", "1" if simple else "0")
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
