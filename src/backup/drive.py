"""Google Drive client: upload, list, download backups.

Uses the same service account the operator already configured for
the Sheets read-only ingest, but with the ``drive.file`` scope so
we only touch files this app created. The folder the operator
designates must be shared with the SA's ``client_email`` (Editor)
for uploads to succeed.

This module imports google-auth lazily so the rest of the package
loads even when the dependency is missing — the GUI surfaces a
clear install instruction in that case.
"""

from __future__ import annotations

import json
from typing import Any

_SCOPES_RW = ["https://www.googleapis.com/auth/drive.file"]
_HTTP_OK = 200
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404


class DriveError(RuntimeError):
    """User-safe failure reaching or writing to Google Drive."""


def _bearer_token(sa_json: str) -> str:
    """Refresh + return an access token from the service-account key."""
    if not (sa_json or "").strip():
        msg = "No service-account key configured."
        raise DriveError(msg)
    try:
        info = json.loads(sa_json)
    except ValueError as exc:
        msg = "Service-account key is not valid JSON."
        raise DriveError(msg) from exc
    try:
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415
    except ImportError as exc:
        msg = (
            "Google auth libraries are not installed. Run a dependency "
            "sync so 'google-auth' is available."
        )
        raise DriveError(msg) from exc
    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES_RW,
        )
        creds.refresh(Request())
    except Exception as exc:
        msg = f"Could not authenticate the service account: {exc}"
        raise DriveError(msg) from exc
    return str(creds.token)


def upload_to_drive(
    sa_json: str, folder_id: str, filename: str, blob: bytes,
) -> dict[str, Any]:
    """Upload ``blob`` as ``filename`` inside the given folder.

    Returns the Drive file metadata (``{"id":..., "name":...}``).
    Raises :class:`DriveError` with an actionable message on any
    error (network, auth, missing folder, permission denied).
    """
    if not folder_id:
        msg = "No Drive folder ID configured."
        raise DriveError(msg)
    import requests  # noqa: PLC0415

    token = _bearer_token(sa_json)
    metadata = {"name": filename, "parents": [folder_id]}

    # Multipart upload (metadata + content in one request).
    boundary = "----rsa-backup-boundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--".encode()

    try:
        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files"
            "?uploadType=multipart&fields=id,name,createdTime,size",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            data=body,
            timeout=120,
        )
    except requests.RequestException as exc:
        msg = f"Network error uploading to Google Drive: {exc}"
        raise DriveError(msg) from exc
    if resp.status_code == _HTTP_FORBIDDEN:
        msg = (
            "Drive denied the upload. Share the backup folder with "
            "the service account's client_email (Editor)."
        )
        raise DriveError(msg)
    if resp.status_code == _HTTP_NOT_FOUND:
        msg = "Drive folder not found — check the folder ID."
        raise DriveError(msg)
    if resp.status_code != _HTTP_OK:
        msg = f"Drive returned HTTP {resp.status_code}: {resp.text[:200]}"
        raise DriveError(msg)
    try:
        return dict(resp.json())
    except ValueError as exc:
        msg = "Drive returned a non-JSON response."
        raise DriveError(msg) from exc


def list_backups(
    sa_json: str, folder_id: str, max_results: int = 50,
) -> list[dict[str, Any]]:
    """List the backups in the configured folder, newest first.

    Used by the GUI to render a restore dropdown and the cleanup
    job to retain only the last N files.
    """
    if not folder_id:
        msg = "No Drive folder ID configured."
        raise DriveError(msg)
    import requests  # noqa: PLC0415

    token = _bearer_token(sa_json)
    query = f"'{folder_id}' in parents and trashed = false"
    params = {
        "q": query,
        "orderBy": "createdTime desc",
        "pageSize": str(max_results),
        "fields": "files(id,name,createdTime,size)",
    }
    try:
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        msg = f"Network error listing Drive folder: {exc}"
        raise DriveError(msg) from exc
    if resp.status_code != _HTTP_OK:
        msg = f"Drive returned HTTP {resp.status_code}: {resp.text[:200]}"
        raise DriveError(msg)
    try:
        files = resp.json().get("files", [])
    except ValueError as exc:
        msg = "Drive returned a non-JSON response."
        raise DriveError(msg) from exc
    return list(files)


def delete_from_drive(sa_json: str, file_id: str) -> None:
    """Delete a Drive file by ID (used by retention cleanup).

    Returns silently on 404 (already gone) so retention sweeps are
    idempotent across runs.
    """
    if not file_id:
        msg = "No Drive file ID supplied."
        raise DriveError(msg)
    import requests  # noqa: PLC0415

    token = _bearer_token(sa_json)
    try:
        resp = requests.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        msg = f"Network error deleting from Google Drive: {exc}"
        raise DriveError(msg) from exc
    # Drive returns 204 No Content on success; 404 means already gone.
    if resp.status_code in {204, _HTTP_NOT_FOUND}:
        return
    msg = f"Drive returned HTTP {resp.status_code}: {resp.text[:200]}"
    raise DriveError(msg)


def download_from_drive(sa_json: str, file_id: str) -> bytes:
    """Download a Drive file's bytes by its file ID."""
    if not file_id:
        msg = "No Drive file ID supplied."
        raise DriveError(msg)
    import requests  # noqa: PLC0415

    token = _bearer_token(sa_json)
    try:
        resp = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
    except requests.RequestException as exc:
        msg = f"Network error downloading from Google Drive: {exc}"
        raise DriveError(msg) from exc
    if resp.status_code == _HTTP_NOT_FOUND:
        msg = "Drive file not found — check the file ID."
        raise DriveError(msg)
    if resp.status_code != _HTTP_OK:
        msg = f"Drive returned HTTP {resp.status_code}: {resp.text[:200]}"
        raise DriveError(msg)
    return resp.content
