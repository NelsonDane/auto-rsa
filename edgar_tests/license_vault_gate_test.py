"""Vault.set_broker / import_env_file honor the license cap."""

from __future__ import annotations

import pytest

from src.gui.core.brokers_meta import get_broker
from src.gui.core.vault import Vault, VaultError
from src.license import _keys, fingerprint, token_store
from edgar_tests.license_test_helpers import (
    fresh_payload,
    public_key_b64,
    sign_token,
)


@pytest.fixture(autouse=True)
def _no_bypass(monkeypatch):
    # These tests assert the broker cap with the license gate ACTIVE. Pin the
    # operator bypass OFF so a module-level RSA_LICENSE_BYPASS=1 leaked by a
    # gui test collected in the same pytest process can't disable the cap under
    # test (test-isolation guard).
    monkeypatch.delenv("RSA_LICENSE_BYPASS", raising=False)


def _account_for(broker_key: str) -> dict[str, str]:
    """Build a dict satisfying a broker's FieldSpec schema."""
    meta = get_broker(broker_key)
    return {f.key: f"test-{f.key}" for f in meta.fields}


@pytest.fixture
def vault(monkeypatch, tmp_path):
    """Unlocked vault with redirected license + salt files."""
    monkeypatch.setattr(
        token_store, "_TOKEN_PATH", tmp_path / "creds" / "license.token",
    )
    monkeypatch.setattr(
        fingerprint, "_SALT_FILE", tmp_path / "creds" / "fp_salt",
    )
    fingerprint.reset_cache_for_tests()
    monkeypatch.setattr(_keys, "PUBLIC_KEY_B64", public_key_b64())
    v = Vault(tmp_path / "vault.json")
    v.initialize("pw")  # creates + unlocks
    yield v
    fingerprint.reset_cache_for_tests()


def _install_tier(tier: str) -> None:
    payload = fresh_payload(tier=tier, hardware_id=fingerprint.hardware_id())
    token_store.save(sign_token(payload))


def test_unlicensed_allows_first_broker(vault):
    vault.set_broker("fennel", [_account_for("fennel")])
    assert vault.configured_broker_keys() == ["fennel"]


def test_unlicensed_refuses_second_broker(vault):
    vault.set_broker("fennel", [_account_for("fennel")])
    with pytest.raises(VaultError) as excinfo:
        vault.set_broker("bbae", [_account_for("bbae")])
    assert "Unlicensed" in str(excinfo.value)
    assert "delete an existing" in str(excinfo.value)
    # The second broker must NOT be persisted.
    assert vault.configured_broker_keys() == ["fennel"]


def test_swap_flow_delete_then_add_works(vault):
    """The operator-approved 'swap' flow under Unlicensed."""
    vault.set_broker("fennel", [_account_for("fennel")])
    vault.delete_broker("fennel")
    vault.set_broker("bbae", [_account_for("bbae")])  # ok
    assert vault.configured_broker_keys() == ["bbae"]


def test_updating_existing_broker_is_always_allowed_even_at_cap(vault):
    """Re-saving an already-configured broker doesn't count as 'add'."""
    vault.set_broker("fennel", [_account_for("fennel")])
    # Updating fennel — still at 1/1 — must not raise.
    vault.set_broker("fennel", [_account_for("fennel")])
    assert vault.configured_broker_keys() == ["fennel"]


def test_advanced_tier_allows_up_to_five(vault):
    _install_tier("advanced")
    five = ("fennel", "bbae", "public", "robinhood", "dspac")
    for k in five:
        vault.set_broker(k, [_account_for(k)])
    # Cap reached — the sixth must refuse.
    with pytest.raises(VaultError) as excinfo:
        vault.set_broker("schwab", [_account_for("schwab")])
    assert "Advanced" in str(excinfo.value)


def test_operator_tier_is_unlimited(vault):
    _install_tier("operator")
    keys = ("fennel", "bbae", "public", "robinhood", "dspac",
            "schwab", "webull", "sofi")
    for k in keys:
        vault.set_broker(k, [_account_for(k)])
    assert len(vault.configured_broker_keys()) == len(keys)


def test_import_env_skips_brokers_past_the_cap(vault, tmp_path):
    """The .env import path enforces the same gate."""
    # Unlicensed: only one broker should land; the rest are reported skipped.
    env = tmp_path / ".env"
    env.write_text(
        "FENNEL=patpat\nBBAE=u:p\nPUBLIC=u:p\n",
        encoding="utf-8",
    )
    imported = vault.import_env_file(env)
    skipped = imported.pop("_skipped", "")
    # Exactly one broker imported; the rest skipped.
    assert len(imported) == 1
    assert skipped  # at least one skipped name listed
    assert len(vault.configured_broker_keys()) == 1
