"""Drive client: error handling + request shape (no real network)."""

from __future__ import annotations

import json

import pytest

from src.backup import drive


class _FakeResp:
    def __init__(self, status: int, body: bytes | str = b"", *, json_body=None):
        self.status_code = status
        self.text = body if isinstance(body, str) else body.decode("utf-8", "replace")
        self.content = body if isinstance(body, bytes) else body.encode()
        self._json_body = json_body

    def json(self):
        if self._json_body is None:
            raise ValueError("not json")
        return self._json_body


@pytest.fixture
def _stub_auth(monkeypatch):
    """Skip the real google-auth flow; pretend any SA key gives a token."""
    monkeypatch.setattr(drive, "_bearer_token", lambda _: "test-token")


def test_upload_round_trip(monkeypatch, _stub_auth):
    captured = {}

    def _post(url, headers, data, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = data
        captured["timeout"] = timeout
        return _FakeResp(200, json_body={
            "id": "file-1", "name": "backup.bin",
            "createdTime": "2026-06-01T00:00:00Z", "size": "12",
        })

    import requests
    monkeypatch.setattr(requests, "post", _post)

    meta = drive.upload_to_drive(
        sa_json="{}", folder_id="FOLDER123",
        filename="backup-2026-06-01.bin", blob=b"\x00\x01\x02\x03",
    )
    assert meta["id"] == "file-1"
    assert "/upload/drive/v3/files" in captured["url"]
    assert "uploadType=multipart" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    # Body contains the metadata JSON with the requested parent folder.
    assert b"FOLDER123" in captured["body"]
    assert b"backup-2026-06-01.bin" in captured["body"]
    assert b"\x00\x01\x02\x03" in captured["body"]


def test_upload_no_folder_id_fails_clearly(_stub_auth):
    with pytest.raises(drive.DriveError) as exc:
        drive.upload_to_drive(sa_json="{}", folder_id="", filename="x", blob=b"y")
    assert "folder" in str(exc.value).lower()


def test_upload_403_returns_actionable_share_message(monkeypatch, _stub_auth):
    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResp(403, "forbidden"),
    )
    with pytest.raises(drive.DriveError) as exc:
        drive.upload_to_drive(sa_json="{}", folder_id="F", filename="x", blob=b"y")
    msg = str(exc.value).lower()
    assert "share" in msg and "client_email" in msg


def test_upload_404_returns_folder_not_found(monkeypatch, _stub_auth):
    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResp(404, "not found"),
    )
    with pytest.raises(drive.DriveError) as exc:
        drive.upload_to_drive(sa_json="{}", folder_id="F", filename="x", blob=b"y")
    assert "folder" in str(exc.value).lower()


def test_list_backups_returns_newest_first(monkeypatch, _stub_auth):
    import requests

    def _get(url, headers, params, timeout):
        assert params["orderBy"] == "createdTime desc"
        assert "'FOLDER1' in parents" in params["q"]
        return _FakeResp(200, json_body={
            "files": [
                {"id": "f2", "name": "newer.bin", "createdTime": "2026-06-02"},
                {"id": "f1", "name": "older.bin", "createdTime": "2026-06-01"},
            ],
        })

    monkeypatch.setattr(requests, "get", _get)
    files = drive.list_backups(sa_json="{}", folder_id="FOLDER1")
    assert [f["name"] for f in files] == ["newer.bin", "older.bin"]


def test_download_returns_raw_bytes(monkeypatch, _stub_auth):
    import requests
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _FakeResp(200, b"\x99\xaa\xbb"),
    )
    blob = drive.download_from_drive(sa_json="{}", file_id="file-99")
    assert blob == b"\x99\xaa\xbb"


def test_download_404_returns_clear_error(monkeypatch, _stub_auth):
    import requests
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _FakeResp(404, "not found"),
    )
    with pytest.raises(drive.DriveError) as exc:
        drive.download_from_drive(sa_json="{}", file_id="missing")
    assert "not found" in str(exc.value).lower()


def test_bearer_token_rejects_blank_sa():
    # No _stub_auth — call the real function.
    with pytest.raises(drive.DriveError) as exc:
        drive._bearer_token("")
    assert "service-account" in str(exc.value).lower()


def test_bearer_token_rejects_bad_json(monkeypatch):
    with pytest.raises(drive.DriveError) as exc:
        drive._bearer_token("not json")
    assert "valid json" in str(exc.value).lower()
