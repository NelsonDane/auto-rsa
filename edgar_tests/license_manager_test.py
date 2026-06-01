"""Manager: tier decision flow + can_add_broker boundaries + grace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.license import _keys, fingerprint, manager, token_store
from edgar_tests.license_test_helpers import (
    fresh_payload,
    public_key_b64,
    sign_token,
)


@pytest.fixture(autouse=True)
def _isolated_creds(monkeypatch, tmp_path):
    """Redirect token + salt I/O into a tmp dir so tests don't touch the real vault."""
    token_path = tmp_path / "creds" / "license.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(token_store, "_TOKEN_PATH", token_path)
    monkeypatch.setattr(fingerprint, "_SALT_FILE", tmp_path / "creds" / "fp_salt")
    fingerprint.reset_cache_for_tests()
    monkeypatch.setattr(_keys, "PUBLIC_KEY_B64", public_key_b64())
    yield
    fingerprint.reset_cache_for_tests()


def _install_token(payload: dict) -> None:
    token_store.save(sign_token(payload))


# --- no token / malformed token --------------------------------------

def test_unlicensed_when_no_token():
    assert manager.current_tier() == "unlicensed"
    assert manager.account_cap() == 1
    assert manager.status_summary()["reason"] == "no token configured"


def test_unlicensed_when_token_unparseable(tmp_path):
    (tmp_path / "creds" / "license.token").write_text(
        "not even json", encoding="utf-8",
    )
    assert manager.current_tier() == "unlicensed"


def test_token_unreadable_surfaces_distinct_error(tmp_path):
    """A corrupt token file must NOT silently look like a fresh
    install — the GUI banner needs to distinguish 'no token yet'
    from 'token broken, fix it'."""
    (tmp_path / "creds" / "license.token").write_text(
        "not even json", encoding="utf-8",
    )
    summary = manager.status_summary()
    assert summary["tier"] == "unlicensed"
    assert summary["token_error"]  # truthy, with a human-safe message
    assert "valid JSON" in summary["token_error"]


def test_no_token_file_has_no_token_error(tmp_path):
    """Fresh install: tier is unlicensed but token_error is None."""
    summary = manager.status_summary()
    assert summary["tier"] == "unlicensed"
    assert summary["token_error"] is None


def test_unlicensed_when_token_signed_by_wrong_key(monkeypatch):
    _install_token(
        fresh_payload(tier="operator", hardware_id=fingerprint.hardware_id()),
    )
    monkeypatch.setattr(_keys, "PUBLIC_KEY_B64", "")  # production unconfigured
    assert manager.current_tier() == "unlicensed"


# --- happy paths ------------------------------------------------------

@pytest.mark.parametrize(
    ("tier", "expected_cap"),
    [("basic", 1), ("advanced", 5), ("operator", None)],
)
def test_valid_token_unlocks_each_tier(tier, expected_cap):
    _install_token(
        fresh_payload(tier=tier, hardware_id=fingerprint.hardware_id()),
    )
    assert manager.current_tier() == tier
    assert manager.account_cap() == expected_cap


def test_status_summary_includes_hardware_id_and_label():
    _install_token(
        fresh_payload(tier="advanced", hardware_id=fingerprint.hardware_id()),
    )
    s = manager.status_summary()
    assert s["tier_label"] == "Advanced"
    assert s["cap_text"] == "5"
    assert s["hardware_id"].startswith("h_")
    assert s["license_id"] == "lic-test-0001"
    assert s["in_grace"] is False


# --- hardware binding -------------------------------------------------

def test_token_bound_to_a_different_machine_is_rejected():
    _install_token(
        fresh_payload(tier="operator", hardware_id="h_someoneelse"),
    )
    assert manager.current_tier() == "unlicensed"
    assert "different machine" in manager.status_summary()["reason"]


# --- expiry + grace ---------------------------------------------------

def test_expired_within_grace_is_still_active_but_flagged():
    now = datetime.now(UTC)
    payload = fresh_payload(tier="advanced", hardware_id=fingerprint.hardware_id())
    # Set expires_at to 2 days ago — inside the 7-day grace window.
    payload["expires_at"] = (now - timedelta(days=2)).isoformat().replace(
        "+00:00", "Z",
    )
    _install_token(payload)
    assert manager.current_tier() == "advanced"
    assert manager.status_summary()["in_grace"] is True


def test_expired_beyond_grace_falls_back_to_unlicensed():
    now = datetime.now(UTC)
    payload = fresh_payload(tier="operator", hardware_id=fingerprint.hardware_id())
    payload["expires_at"] = (now - timedelta(days=30)).isoformat().replace(
        "+00:00", "Z",
    )
    _install_token(payload)
    assert manager.current_tier() == "unlicensed"
    assert "beyond grace" in manager.status_summary()["reason"]


# --- can_add_broker boundaries ----------------------------------------

@pytest.mark.parametrize(
    ("tier", "current_count", "expected"),
    [
        # Basic / Unlicensed cap = 1.
        ("basic", 0, True),
        ("basic", 1, False),
        # Advanced cap = 5.
        ("advanced", 4, True),
        ("advanced", 5, False),
        # Operator unlimited.
        ("operator", 100, True),
    ],
)
def test_can_add_broker_at_each_boundary(tier, current_count, expected):
    _install_token(
        fresh_payload(tier=tier, hardware_id=fingerprint.hardware_id()),
    )
    ok, reason = manager.can_add_broker(current_count)
    assert ok is expected, reason
    if not expected:
        assert reason
        assert "delete an existing one" in reason


def test_can_add_broker_unlicensed_default():
    # No token installed; defaults to Unlicensed (cap 1).
    assert manager.can_add_broker(0) == (True, None)
    ok, reason = manager.can_add_broker(1)
    assert ok is False
    assert "Unlicensed" in reason
