"""RSA_LICENSE_BYPASS=1 disables the broker cap for self-hosted ops."""

from __future__ import annotations

import pytest

from src.license import account_cap, can_add_broker, current_tier, status_summary
from src.license.manager import _BYPASS_ENV


@pytest.fixture
def _enable_bypass(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, "1")


@pytest.fixture
def _disable_bypass(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)


def test_bypass_flips_cap_to_unlimited(_enable_bypass):
    """With the env var set, account_cap returns None regardless of
    whether a real license token is on disk."""
    assert account_cap() is None


def test_bypass_reports_operator_tier(_enable_bypass):
    """Banner should show as 'operator' so the rest of the UI reads
    consistently — without this, current_tier() would return
    'unlicensed' and the GUI status caption would still nag."""
    assert current_tier() == "operator"


def test_bypass_can_add_broker_always_true(_enable_bypass):
    """The cap-check call site (Vault.set_broker) must allow every
    add regardless of current_count."""
    for count in (0, 1, 5, 100, 1000):
        ok, reason = can_add_broker(count)
        assert ok is True, f"count={count} should be allowed under bypass"
        assert reason is None


def test_bypass_summary_exposes_bypass_marker(_enable_bypass):
    """status_summary should let downstream renderers tell bypass
    apart from a real Operator license. license_id='BYPASS' is the
    signal used by the GUI banner."""
    info = status_summary()
    assert info["license_id"] == "BYPASS"
    assert info["tier"] == "operator"
    assert info["tier_label"] == "Operator"
    assert info["cap"] is None
    assert info["cap_text"] == "∞"
    assert "RSA_LICENSE_BYPASS=1" in info["reason"]
    assert info["token_error"] is None
    assert info["in_grace"] is False


def test_bypass_accepts_truthy_variants(monkeypatch):
    """'1' / 'true' / 'yes' / 'on' all enable; anything else doesn't."""
    for value in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv(_BYPASS_ENV, value)
        assert account_cap() is None, f"{value!r} should enable bypass"
    for value in ("0", "false", "no", "off", "", "  "):
        monkeypatch.setenv(_BYPASS_ENV, value)
        # Without a real token, the cap falls back to the unlicensed
        # default (1), not None.
        assert account_cap() == 1, f"{value!r} should NOT enable bypass"


def test_no_bypass_means_unlicensed_default(_disable_bypass):
    """Sanity: when the env var is unset (the production posture),
    behavior matches the existing unlicensed flow exactly."""
    assert current_tier() == "unlicensed"
    assert account_cap() == 1
    ok, _reason = can_add_broker(0)
    assert ok is True
    ok, reason = can_add_broker(1)
    assert ok is False
    assert "Unlicensed" in reason
