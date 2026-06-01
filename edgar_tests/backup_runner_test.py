"""End-to-end backup runner: bundle + upload + retention sweep."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from src.backup import bundle, config, drive, runner


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "vault.json").write_bytes(b'{"version":2}')
    (creds / "ledger.db").write_bytes(b"sqlite header...")
    (creds / "license.token").write_bytes(b'{"payload":{}}')
    monkeypatch.setattr(runner, "_CREDS_DIR", creds)
    monkeypatch.setattr(config, "_CONFIG_PATH", tmp_path / "backup_config.json")


def test_backup_filename_is_sortable():
    now = _dt.datetime(2026, 6, 1, 14, 30, 45, tzinfo=_dt.UTC)
    name = runner.backup_filename(now=now)
    assert name == "rsa-backup-2026-06-01T14-30-45Z.bin"


def test_run_backup_uploads_and_returns_summary(monkeypatch):
    config.save(drive_folder_id="FOLDER", passphrase="pw", retention=3)
    uploaded = {}

    def _fake_upload(sa_json, folder_id, filename, blob):
        uploaded.update(folder_id=folder_id, filename=filename, blob=blob)
        return {"id": "drive-id-1", "name": filename, "size": str(len(blob))}

    monkeypatch.setattr(drive, "upload_to_drive", _fake_upload)
    monkeypatch.setattr(drive, "list_backups", lambda *a, **k: [])

    summary = runner.run_backup(sa_json="{}")
    assert summary["drive_file_id"] == "drive-id-1"
    assert summary["uploaded"].startswith("rsa-backup-")
    assert summary["size_bytes"] > 0
    assert uploaded["folder_id"] == "FOLDER"
    # Bundle that was uploaded is decryptable with the configured passphrase.
    dest = Path(uploaded["filename"]).parent  # not actually a path; sentinel
    dest = runner._CREDS_DIR / "round_trip"
    files = bundle.restore_bundle("pw", uploaded["blob"], dest)
    assert "vault.json" in files


def test_run_backup_without_config_raises(monkeypatch):
    monkeypatch.setattr(drive, "upload_to_drive", lambda *a, **k: {"id": "x"})
    with pytest.raises(bundle.BackupError) as exc:
        runner.run_backup(sa_json="{}")
    assert "not configured" in str(exc.value).lower()


def test_run_backup_retention_deletes_older_files(monkeypatch):
    config.save(drive_folder_id="F", passphrase="p", retention=2)

    monkeypatch.setattr(
        drive, "upload_to_drive",
        lambda *a, **k: {"id": "new-id", "name": a[2]},
    )
    # 5 existing files (newest-first); retention=2 means keep 2, delete 3.
    monkeypatch.setattr(
        drive, "list_backups",
        lambda *a, **k: [
            {"id": "f5", "name": "fifth"},
            {"id": "f4", "name": "fourth"},
            {"id": "f3", "name": "third"},
            {"id": "f2", "name": "second"},
            {"id": "f1", "name": "first"},
        ],
    )
    deleted: list[str] = []
    monkeypatch.setattr(
        drive, "delete_from_drive",
        lambda _sa, fid: deleted.append(fid),
    )
    summary = runner.run_backup(sa_json="{}")
    # Newest 2 kept (f5, f4); older 3 deleted.
    assert deleted == ["f3", "f2", "f1"]
    assert len(summary["retention_deleted"]) == 3


def test_run_backup_retention_failure_is_swallowed(monkeypatch):
    """One stale-delete failure shouldn't fail the whole backup."""
    config.save(drive_folder_id="F", passphrase="p", retention=1)
    monkeypatch.setattr(
        drive, "upload_to_drive",
        lambda *a, **k: {"id": "new"},
    )
    monkeypatch.setattr(
        drive, "list_backups",
        lambda *a, **k: [{"id": "f2"}, {"id": "f1"}],
    )

    def _fail_delete(_sa, _fid):
        msg = "drive transient error"
        raise drive.DriveError(msg)

    monkeypatch.setattr(drive, "delete_from_drive", _fail_delete)
    # Should NOT raise.
    summary = runner.run_backup(sa_json="{}")
    assert summary["retention_deleted"] == []


def test_run_restore_round_trips(monkeypatch, tmp_path):
    config.save(drive_folder_id="F", passphrase="pw", retention=1)
    uploaded_blob = {}

    def _fake_upload(sa, folder, name, blob):
        uploaded_blob["blob"] = blob
        return {"id": "drive-id", "name": name}

    monkeypatch.setattr(drive, "upload_to_drive", _fake_upload)
    monkeypatch.setattr(drive, "list_backups", lambda *a, **k: [])
    runner.run_backup(sa_json="{}")

    monkeypatch.setattr(
        drive, "download_from_drive",
        lambda _sa, _fid: uploaded_blob["blob"],
    )
    dest = tmp_path / "restored"
    written = runner.run_restore(
        sa_json="{}", file_id="drive-id", passphrase="pw", dest_dir=dest,
    )
    assert set(written) == {"vault.json", "ledger.db", "license.token"}
