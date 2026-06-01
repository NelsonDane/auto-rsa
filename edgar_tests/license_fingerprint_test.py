"""Hardware fingerprint stability + race safety."""

from __future__ import annotations

import os

import pytest

from src.license import fingerprint


@pytest.fixture(autouse=True)
def _isolated_salt(monkeypatch, tmp_path):
    monkeypatch.setattr(fingerprint, "_SALT_FILE", tmp_path / "fp_salt")
    fingerprint.reset_cache_for_tests()
    yield
    fingerprint.reset_cache_for_tests()


def test_hardware_id_is_stable_across_calls():
    first = fingerprint.hardware_id()
    fingerprint.reset_cache_for_tests()
    assert fingerprint.hardware_id() == first


def test_hardware_id_format():
    hid = fingerprint.hardware_id()
    assert hid.startswith("h_")
    assert len(hid) > 4  # not just the prefix


def test_salt_persists_to_disk(tmp_path):
    fingerprint.hardware_id()
    assert (tmp_path / "fp_salt").is_file()
    assert (tmp_path / "fp_salt").stat().st_size == fingerprint._SALT_LEN


def test_salt_race_is_idempotent(tmp_path):
    """Two simulated first-starts must converge on the same salt.

    Before the O_EXCL fix, both calls would generate a fresh salt and
    the last write would win, leaving the loser's in-memory salt out
    of sync with the persisted one — tokens silently invalidate on
    next restart. The fix ensures both processes end up with the salt
    that won the race.
    """
    # Simulate process A: generates a salt, writes it, gets back ITS salt.
    salt_a = fingerprint._ensure_salt()
    # Simulate process B starting "at the same time" but without
    # benefit of the cache (different process). Should re-read what A
    # wrote, NOT generate a new one.
    fingerprint.reset_cache_for_tests()
    salt_b = fingerprint._ensure_salt()
    assert salt_a == salt_b


def test_salt_race_winner_persists(tmp_path):
    """If the file already exists with valid contents, _ensure_salt
    must read it instead of overwriting."""
    custom_salt = b"\x99" * fingerprint._SALT_LEN
    (tmp_path / "fp_salt").write_bytes(custom_salt)
    assert fingerprint._ensure_salt() == custom_salt
    # And the file is unchanged.
    assert (tmp_path / "fp_salt").read_bytes() == custom_salt


def test_salt_race_o_excl_fallback(tmp_path, monkeypatch):
    """If a competing process creates the file between the existence
    check and os.open, the FileExistsError handler must re-read."""
    competing_salt = b"\x42" * fingerprint._SALT_LEN
    original_open = os.open
    state = {"called": False}

    def _racing_open(path, flags, mode=0o600):
        # On the first O_CREAT|O_EXCL attempt, simulate that another
        # process already created the file with a different salt.
        if not state["called"] and (flags & os.O_EXCL):
            state["called"] = True
            with open(path, "wb") as f:
                f.write(competing_salt)
            return original_open(path, flags, mode)  # will raise FileExistsError
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "open", _racing_open)
    salt = fingerprint._ensure_salt()
    assert salt == competing_salt
