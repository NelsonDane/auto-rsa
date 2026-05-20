"""EDGAR -> GUI_QUEUE producer.

Ties the M3 pieces together: EFTS discovery -> filing enrichment ->
deterministic classify -> reverse-split/ratio/date -> pre-split
deadline -> dedupe keys -> the exact GUI_QUEUE row schema the M2 GUI
already ingests. Runs *alongside* the Apps Script (augment, not
replace): same schema, idempotent by article_key, only alert-worthy
rows are emitted (the bot still buys ROUND_UP only).

Writing the sheet needs the read/write Sheets scope; discovery and row
building are network-isolated and unit-tested without Google.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from src.edgar.classify import (
    derive_fractional_expectation,
    parse_fractional_policy,
    parse_reverse_split,
    should_alert_for_rsa,
)
from src.edgar.fetch import (
    DEFAULT_FORMS,
    DEFAULT_QUERIES,
    cik_to_ticker,
    efts_search,
    fetch_filing_text,
)
from src.edgar.keys import article_key, split_key
from src.edgar.market_calendar import presplit_deadline_text

GUI_QUEUE_HEADER = (
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
_LOW_CONF = 0.50


class Play(NamedTuple):
    """A classified reverse-split play ready for the GUI_QUEUE."""

    ticker: str
    ratio: str
    effective_date: str
    fractional_policy: str
    confidence: float
    expectation: str
    source: str
    key: str
    split_key: str
    link: str


def _classify_hit(text: str, title: str) -> tuple[str, float, str]:
    """Best policy from filing text, falling back to the title."""
    fp = parse_fractional_policy(text)
    if fp.policy == "UNSPECIFIED" or fp.conf < _LOW_CONF:
        alt = parse_fractional_policy(title)
        if alt.policy != "UNSPECIFIED" and alt.conf > fp.conf:
            fp = alt
    return fp.policy, fp.conf, fp.evidence


def discover(
    *,
    window_days: int = 14,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    enrich: bool = True,
) -> list[Play]:
    """Search EDGAR and return alert-worthy, de-duplicated plays."""
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=window_days)).isoformat()
    end = today.isoformat()

    seen_acc: set[str] = set()
    seen_split: set[str] = set()
    plays: list[Play] = []

    for q in queries:
        for hit in efts_search(q, start, end, forms):
            if hit.accession in seen_acc:
                continue
            seen_acc.add(hit.accession)

            body = fetch_filing_text(hit.link) if enrich else ""
            text = body or hit.title
            policy, conf, _ = _classify_hit(text, hit.title)
            if not should_alert_for_rsa(policy, conf):
                continue

            rs = parse_reverse_split(text or hit.title)
            ticker = (hit.ticker or cik_to_ticker(hit.cik) or "").upper()
            if not ticker or not rs.ratio:
                continue
            expectation = derive_fractional_expectation(
                policy,
                is_reverse_split=True,
                ratio=rs.ratio,
                evidence_text=text,
            )
            sk = split_key(ticker, rs.ratio, rs.effective_date or "", policy)
            if sk and sk in seen_split:
                continue
            if sk:
                seen_split.add(sk)
            plays.append(
                Play(
                    ticker=ticker,
                    ratio=rs.ratio,
                    effective_date=rs.effective_date or "",
                    fractional_policy=policy,
                    confidence=round(conf, 2),
                    expectation=expectation,
                    source="SEC_EFTS",
                    key=article_key(hit.link, hit.title),
                    split_key=sk,
                    link=hit.link,
                ),
            )
    return plays


def to_gui_rows(plays: list[Play]) -> list[list[object]]:
    """Render plays as GUI_QUEUE rows (matches writeGuiQueue_ exactly)."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    return [
        [
            now,
            p.ticker,
            "buy",
            p.ratio,
            p.effective_date,
            presplit_deadline_text(p.effective_date),
            p.fractional_policy,
            p.confidence,
            p.source,
            p.key,
            "PENDING",
        ]
        for p in plays
    ]


def append_gui_queue(
    service_account_json: str,
    spreadsheet_id: str,
    rows: list[list[object]],
    worksheet: str = "GUI_QUEUE",
) -> int:
    """Append new rows to GUI_QUEUE, idempotent by KEY. Returns # written.

    Read+write Sheets scope. Existing KEYs are skipped so re-runs and
    overlap with the Apps Script producer never double-queue a play.
    """
    if not rows:
        return 0
    try:
        import requests  # noqa: PLC0415
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415
    except ImportError as exc:
        msg = "google-auth not installed (dependency sync needed)."
        raise RuntimeError(msg) from exc

    info = json.loads(service_account_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    creds.refresh(Request())
    auth = {"Authorization": f"Bearer {creds.token}"}
    base = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    )

    existing: set[str] = set()
    got = requests.get(
        f"{base}/values/{worksheet}!J:J", headers=auth, timeout=30,
    )
    if got.status_code == 200:  # noqa: PLR2004
        existing = {str(r[0]) for r in got.json().get("values", []) if r}

    fresh = [r for r in rows if str(r[9]) not in existing]
    if not fresh:
        return 0
    requests.post(
        f"{base}/values/{worksheet}!A1:append",
        headers=auth,
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": fresh},
        timeout=30,
    ).raise_for_status()
    return len(fresh)
