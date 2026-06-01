"""Backup config IO: save, load, validate, clear."""

from __future__ import annotations

import os
import stat

import pytest

from src.backup import config


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_CONFIG_PATH", tmp_path / "backup_config.json")


def test_load_returns_empty_when_no_file():
    assert config.load() == {}


def test_save_then_load_round_trip():
    config.save(drive_folder_id="FOLDER1", passphrase="pw", retention=5)
    cfg = config.load()
    assert cfg["drive_folder_id"] == "FOLDER1"
    assert cfg["passphrase"] == "pw"
    assert cfg["retention"] == 5


def test_save_uses_default_retention_when_zero():
    config.save(drive_folder_id="F", passphrase="p", retention=0)
    assert config.load()["retention"] == config.DEFAULT_RETENTION


def test_empty_folder_id_refuses_to_save():
    with pytest.raises(ValueError, match="folder"):
        config.save(drive_folder_id="", passphrase="x")


def test_empty_passphrase_refuses_to_save():
    with pytest.raises(ValueError, match="passphrase"):
        config.save(drive_folder_id="F", passphrase="")


def test_corrupt_file_returns_empty_not_raise():
    config.path().parent.mkdir(parents=True, exist_ok=True)
    config.path().write_text("not even json", encoding="utf-8")
    assert config.load() == {}


def test_is_configured_only_true_when_both_set():
    assert not config.is_configured()
    config.save(drive_folder_id="F", passphrase="p")
    assert config.is_configured()


def test_clear_removes_the_file():
    config.save(drive_folder_id="F", passphrase="p")
    assert config.path().is_file()
    config.clear()
    assert not config.path().is_file()
    # Clearing again is a no-op (no exception).
    config.clear()


def test_save_chmods_600_on_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX-only file mode test")
    config.save(drive_folder_id="F", passphrase="p")
    mode = stat.S_IMODE(config.path().stat().st_mode)
    assert mode == 0o600
