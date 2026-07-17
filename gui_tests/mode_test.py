"""Simple Mode flag resolution: env > sentinel > build default."""

import pytest

from src.gui.core import mode


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(mode, "_FLAG_PATH", tmp_path / "simple_mode.flag")
    monkeypatch.delenv("RSA_SIMPLE_MODE", raising=False)
    # Build default off unless a test overrides it.
    monkeypatch.setattr("src.license._keys.SIMPLE_MODE_DEFAULT", False, raising=False)
    yield


def test_default_off():
    assert mode.simple_mode() is False


def test_env_on(monkeypatch):
    monkeypatch.setenv("RSA_SIMPLE_MODE", "1")
    assert mode.simple_mode() is True


def test_env_off_overrides_build_default(monkeypatch):
    monkeypatch.setattr("src.license._keys.SIMPLE_MODE_DEFAULT", True, raising=False)
    monkeypatch.setenv("RSA_SIMPLE_MODE", "0")
    assert mode.simple_mode() is False  # env wins


def test_build_default_on(monkeypatch):
    monkeypatch.setattr("src.license._keys.SIMPLE_MODE_DEFAULT", True, raising=False)
    assert mode.simple_mode() is True


def test_sentinel_flag_toggles(monkeypatch):
    assert mode.simple_mode() is False
    mode.set_simple_mode(enabled=True)
    assert mode.simple_mode_flag_path().is_file()
    assert mode.simple_mode() is True
    mode.set_simple_mode(enabled=False)
    assert not mode.simple_mode_flag_path().is_file()
    assert mode.simple_mode() is False


def test_env_beats_sentinel(monkeypatch):
    mode.set_simple_mode(enabled=True)  # sentinel says on
    monkeypatch.setenv("RSA_SIMPLE_MODE", "0")  # env says off
    assert mode.simple_mode() is False


def test_friend_build_forces_simple_mode(monkeypatch):
    # SEC-3: a friend build ignores the RSA_SIMPLE_MODE=0 downgrade so the
    # advanced UI / bypass toggle can't be re-exposed.
    monkeypatch.setattr("src.license._keys.REQUIRE_LICENSE_TO_TRADE", True, raising=False)
    monkeypatch.setenv("RSA_SIMPLE_MODE", "0")
    assert mode.simple_mode() is True
    mode.set_simple_mode(enabled=False)
    assert mode.simple_mode() is True  # flag-off also ignored in friend build
