"""License tab renders and surfaces the kill-switch state (no network)."""

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


def _app(monkeypatch, *, killed: bool):
    # No network: pin the server + kill-switch state.
    monkeypatch.setattr(lic, "server_url", lambda: "https://example.test")
    monkeypatch.setattr(
        lic, "killswitch_status",
        lambda: {
            "active": killed,
            "message": "Paused for a fix" if killed else "",
            "min_app_version": "",
            "reachable": True,
        },
    )
    d = Path(tempfile.mkdtemp())
    v = Vault(d / "v.json")
    v.initialize("pw")
    v.set_broker("bbae", [{"username": "u", "password": "p"}])
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = v
    at.session_state["runner"] = TradeRunner(v)
    at.session_state["active_section"] = "🔑 License"
    return at


def test_license_tab_renders_clean(monkeypatch):
    at = _app(monkeypatch, killed=False)
    at.run()
    assert not at.exception, at.exception
    # Bypass is on in tests, so the tier metric reads Operator (bypass).
    assert any("Operator" in (m.value or "") for m in at.metric), [m.value for m in at.metric]
    # An Activate button exists (friend-facing activation).
    assert any("Activate" in (b.label or "") for b in at.button)


def test_license_tab_shows_kill_banner(monkeypatch):
    at = _app(monkeypatch, killed=True)
    at.run()
    assert not at.exception, at.exception
    assert any("PAUSED" in (e.value or "") for e in at.error), [e.value for e in at.error]
