"""Fidelity unattended-TOTP wiring + the no-blocking-input guard."""

import builtins
import types

from src.gui.core.brokers_meta import get_broker


def test_fidelity_creds_assemble_with_totp_segment():
    meta = get_broker("fidelity")
    # TOTP present -> user:pass:SECRET (3rd segment fidelity_init passes
    # straight to the vendored lib, which runs the full pyotp flow).
    assert meta.assemble_account(
        {"username": "u@e.com", "password": "pw", "totp_secret": "JBSWY3DP"},
    ) == "u@e.com:pw:JBSWY3DP"
    # Blank -> "NA" (the lib treats NA as "no TOTP, fall back to SMS").
    assert meta.assemble_account(
        {"username": "u@e.com", "password": "pw", "totp_secret": ""},
    ) == "u@e.com:pw:NA"


def test_unattended_without_totp_escalates_not_blocks(monkeypatch, capsys):
    from src.brokerages import fidelity_api

    class _FakeFid:
        def __init__(self, **_kw):
            self.page = types.SimpleNamespace(url="https://fidelity/login")

        def login(self, _u, _p, _t):
            return (True, False)  # SMS 2FA required (no/NA TOTP)

    called: list[int] = []
    monkeypatch.setattr(fidelity_api.fidelity, "FidelityAutomation", _FakeFid)
    monkeypatch.setattr(builtins, "input", lambda *_a: called.append(1) or "x")
    monkeypatch.setenv("RSA_UNATTENDED", "1")

    result = fidelity_api.fidelity_init("user:pass", "Fidelity 1")

    # Unattended: NEVER prompt; fail fast as a (None) login failure with
    # an actionable message the executor surfaces as skip+alert.
    assert called == [], "input() must not be called when unattended"
    assert result is None
    out = capsys.readouterr().out.lower()
    assert "unattended" in out and "totp secret" in out
    assert "enter code" not in out


def test_attended_still_allows_prompt(monkeypatch):
    # Sanity: without RSA_UNATTENDED the existing interactive path is
    # untouched (input() is reached, here stubbed to a code).
    from src.brokerages import fidelity_api

    class _FakeFid:
        def __init__(self, **_kw):
            self.page = types.SimpleNamespace(url="https://fidelity/login")

        def login(self, _u, _p, _t):
            return (True, False)

        def login_2FA(self, code):
            self._code = code
            msg = "stop-after-2fa"  # short-circuit before getAccountInfo
            raise RuntimeError(msg)

    seen: list[str] = []
    monkeypatch.setattr(fidelity_api.fidelity, "FidelityAutomation", _FakeFid)
    monkeypatch.setattr(builtins, "input", lambda *_a: seen.append("asked") or "123456")
    monkeypatch.delenv("RSA_UNATTENDED", raising=False)

    fidelity_api.fidelity_init("user:pass", "Fidelity 1")
    assert seen == ["asked"]  # attended prompt path preserved
