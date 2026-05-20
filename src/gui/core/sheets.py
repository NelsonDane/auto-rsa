"""Read-only ingest of the GUI_QUEUE Google Sheet (M2).

The upstream Apps Script appends one row per detected reverse-split
play to a ``GUI_QUEUE`` tab and dedupes by ``KEY``. This module reads
that tab with a Google **service account** (read-only scope) and parses
rows into :class:`Signal`. It never writes back — accounting lives in
the local execution ledger, keyed by the same ``KEY``.

``google-auth`` is imported lazily inside :func:`fetch_signals` so the
module (and the parsing logic / tests) work even when the dependency
isn't installed yet.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

# GUI_QUEUE header as written by writeGuiQueue_ in the Apps Script.
_HEADER = (
    "CREATED_AT",
    "TICKER",
    "ACTION",
    "RATIO",
    "EFFECTIVE_DATE",
    "PRESPLIT_DEADLINE",
    "FRACTIONAL_POLICY",
    "CONFIDENCE",
    "SOURCE",
    "KEY",
    "STATUS",
)
_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_HTTP_OK = 200
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404


class SheetsError(RuntimeError):
    """Any failure reaching or parsing the GUI_QUEUE sheet (message is user-safe)."""


class Signal(NamedTuple):
    """One reverse-split play row from GUI_QUEUE."""

    created_at: str
    ticker: str
    action: str
    ratio: str
    effective_date: str
    presplit_deadline: str
    fractional_policy: str
    confidence: str
    source: str
    key: str
    status: str


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Accept a full Sheets URL or a bare ID and return the ID."""
    s = (url_or_id or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    return m.group(1) if m else s


def parse_values(values: list[list[object]]) -> list[Signal]:
    """Turn raw ``values`` (incl. header row) into Signals.

    Column order is resolved by header name when the header is present
    so a reordered sheet still maps correctly; otherwise positional
    order is assumed. Rows missing a TICKER or KEY are skipped.
    """
    if not values:
        return []
    header = [str(c).strip().upper() for c in values[0]]
    is_header = "KEY" in header and "TICKER" in header
    if is_header:
        idx = {name: header.index(name) for name in header}
        rows = values[1:]
    else:
        idx = {name: i for i, name in enumerate(_HEADER)}
        rows = values

    def cell(row: list[object], name: str) -> str:
        i = idx.get(name)
        if i is None or i >= len(row):
            return ""
        return str(row[i]).strip()

    out: list[Signal] = []
    for row in rows:
        if not row:
            continue
        ticker = cell(row, "TICKER").upper()
        key = cell(row, "KEY")
        if not ticker or not key:
            continue
        out.append(
            Signal(
                created_at=cell(row, "CREATED_AT"),
                ticker=ticker,
                action=(cell(row, "ACTION") or "buy").lower(),
                ratio=cell(row, "RATIO"),
                effective_date=cell(row, "EFFECTIVE_DATE"),
                presplit_deadline=cell(row, "PRESPLIT_DEADLINE"),
                fractional_policy=cell(row, "FRACTIONAL_POLICY"),
                confidence=cell(row, "CONFIDENCE"),
                source=cell(row, "SOURCE"),
                key=key,
                status=cell(row, "STATUS"),
            ),
        )
    return out


def fetch_signals(  # noqa: C901
    service_account_json: str,
    spreadsheet_id: str,
    worksheet: str = "GUI_QUEUE",
) -> list[Signal]:
    """Fetch and parse GUI_QUEUE rows. Read-only; never writes back.

    Raises :class:`SheetsError` with a user-safe message on any auth,
    network, or parsing failure.
    """
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    if not service_account_json.strip():
        msg = "No service-account key configured."
        raise SheetsError(msg)
    if not spreadsheet_id:
        msg = "No spreadsheet ID/URL configured."
        raise SheetsError(msg)
    try:
        info = json.loads(service_account_json)
    except ValueError as exc:
        msg = "Service-account key is not valid JSON."
        raise SheetsError(msg) from exc

    try:
        import requests  # noqa: PLC0415
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415
    except ImportError as exc:  # dependency not installed yet
        msg = (
            "Google auth libraries are not installed. Run a dependency "
            "sync so 'google-auth' is available."
        )
        raise SheetsError(msg) from exc

    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[_READONLY_SCOPE],
        )
        creds.refresh(Request())
    except Exception as exc:
        msg = f"Could not authenticate the service account: {exc}"
        raise SheetsError(msg) from exc

    rng = requests.utils.quote(worksheet or "GUI_QUEUE", safe="")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{rng}"
    )
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        msg = f"Network error reaching Google Sheets: {exc}"
        raise SheetsError(msg) from exc
    if resp.status_code == _HTTP_FORBIDDEN:
        msg = (
            "Access denied. Share the spreadsheet with the service "
            "account's client_email (Viewer is enough)."
        )
        raise SheetsError(msg)
    if resp.status_code == _HTTP_NOT_FOUND:
        msg = "Spreadsheet or worksheet not found — check the ID and tab name."
        raise SheetsError(msg)
    if resp.status_code != _HTTP_OK:
        msg = f"Google Sheets returned HTTP {resp.status_code}: {resp.text[:200]}"
        raise SheetsError(msg)
    try:
        values = resp.json().get("values", [])
    except ValueError as exc:
        msg = "Google Sheets returned a non-JSON response."
        raise SheetsError(msg) from exc
    return parse_values(values)
