"""First-run setup wizard: shows on the friend build until finished."""

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


def _app(monkeypatch, tmp_path, *, complete: bool, unlocked: bool = False):
    monkeypatch.setenv("RSA_SIMPLE_MODE", "1")
    monkeypatch.setattr(wizard, "_FLAG_PATH", tmp_path / "setup_complete.flag")
    if complete:
        wizard.mark_setup_complete()
    monkeypatch.setattr(
        lic, "killswitch_status",
        lambda: {"active": False, "message": "", "min_app_version": "", "reachable": True},
    )
    v = Vault(tmp_path / "v.json")
    if unlocked:
        v.initialize("pw")
    at = AppTest.from_file(APP, default_timeout=45)
    at.session_state["vault"] = v
    at.session_state["runner"] = TradeRunner(v)
    return at


def test_wizard_shows_when_incomplete(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, complete=False)
    at.run()
    assert not at.exception, at.exception
    assert any("let's get you set up" in (m.value or "").lower() for m in at.subheader)
    assert any("Get started" in (b.label or "") for b in at.button)


def test_wizard_hidden_when_complete(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, complete=True, unlocked=True)
    at.run()
    assert not at.exception, at.exception
    # Normal UI instead of the wizard.
    assert not any("Get started" in (b.label or "") for b in at.button)


def test_get_started_advances_to_vault_step(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, complete=False)
    at.run()
    [b for b in at.button if "Get started" in (b.label or "")][0].click()
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["wizard_step"] == 1
    assert any("Protect your logins" in (m.value or "") for m in at.markdown)


def test_skip_marks_complete(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, complete=False)
    at.run()
    [b for b in at.button if "Skip setup" in (b.label or "")][0].click()
    at.run()
    assert not at.exception, at.exception
    assert wizard.setup_complete()  # flag written -> wizard won't show again
