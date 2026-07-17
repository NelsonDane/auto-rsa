"""RSA_LICENSE_BYPASS env var + sentinel-file disable the broker cap."""

from __future__ import annotations

import pytest

from src.license import (
    account_cap,
    bypass_flag_path,
    can_add_broker,
    current_tier,
    set_bypass_flag,
    status_summary,
)
from src.license import manager as license_manager
from src.license.manager import _BYPASS_ENV


@pytest.fixture
def _enable_bypass(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, "1")


@pytest.fixture
def _disable_bypass(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)


@pytest.fixture
def _isolated_flag(monkeypatch, tmp_path):
    """Redirect the sentinel-file path so tests don't touch creds/."""
    monkeypatch.setattr(
        license_manager, "_BYPASS_FLAG_PATH",
        tmp_path / "license_bypass.flag",
    )
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


# --- Sentinel-file bypass (GUI-toggleable, no env var needed) ---------

def test_set_bypass_flag_creates_file_and_lifts_cap(_isolated_flag):
    """Operator turns on the toggle in the GUI -> file appears
    -> account_cap drops the limit."""
    assert account_cap() == 1  # baseline: unlicensed
    set_bypass_flag(enabled=True)
    assert bypass_flag_path().is_file()
    assert account_cap() is None
    assert current_tier() == "operator"


def test_set_bypass_flag_disabled_removes_file_and_restores_cap(
    _isolated_flag,
):
    set_bypass_flag(enabled=True)
    assert account_cap() is None
    set_bypass_flag(enabled=False)
    assert not bypass_flag_path().is_file()
    # Back to unlicensed default.
    assert account_cap() == 1


def test_set_bypass_flag_is_idempotent(_isolated_flag):
    """Toggling on twice / off twice must not raise — the GUI
    might call set_bypass_flag on every rerun."""
    set_bypass_flag(enabled=True)
    set_bypass_flag(enabled=True)  # should not raise
    assert bypass_flag_path().is_file()
    set_bypass_flag(enabled=False)
    set_bypass_flag(enabled=False)  # should not raise
    assert not bypass_flag_path().is_file()


def test_env_var_overrides_flag_off(_isolated_flag, monkeypatch):
    """If the operator unsets the file but the env var is still
    set, bypass remains on (env wins). Either path enables; both
    must be cleared to disable."""
    set_bypass_flag(enabled=False)
    monkeypatch.setenv(_BYPASS_ENV, "1")
    assert account_cap() is None


def test_either_path_enables_bypass(_isolated_flag, monkeypatch):
    """ENV-only on -> bypass. FILE-only on -> bypass. The two OR
    together for backward compat (existing operators who already
    set the env var keep working)."""
    # ENV alone:
    monkeypatch.setenv(_BYPASS_ENV, "1")
    assert not bypass_flag_path().is_file()
    assert account_cap() is None
    monkeypatch.delenv(_BYPASS_ENV)

    # FILE alone:
    set_bypass_flag(enabled=True)
    assert account_cap() is None
    set_bypass_flag(enabled=False)
    assert account_cap() == 1


def test_status_summary_reflects_flag_bypass(_isolated_flag):
    set_bypass_flag(enabled=True)
    info = status_summary()
    assert info["license_id"] == "BYPASS"
    assert info["tier"] == "operator"
    assert info["cap"] is None


# --- SEC-1: the bypass must be UNREACHABLE in a friend build ----------

def test_friend_build_ignores_env_bypass(monkeypatch):
    """A friend build (REQUIRE_LICENSE_TO_TRADE) must ignore
    RSA_LICENSE_BYPASS so a friend can't lift their own cap."""
    from src.license import _keys

    monkeypatch.setenv(_BYPASS_ENV, "1")
    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", True, raising=False)
    assert current_tier() == "unlicensed"  # NOT operator
    assert account_cap() == 1               # cap NOT lifted


def test_friend_build_ignores_flag_bypass(_isolated_flag, monkeypatch):
    from src.license import _keys

    set_bypass_flag(enabled=True)
    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", True, raising=False)
    assert account_cap() == 1               # flag ignored in friend build
    assert current_tier() == "unlicensed"
