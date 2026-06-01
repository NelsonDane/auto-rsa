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
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPECIAL_DIV,
    SIGNAL_TYPE_SPIN_OFF,
    derive_fractional_expectation,
    parse_fractional_policy,
    parse_reverse_split,
    parse_special_dividend,
    parse_spin_off,
    should_alert_for_rsa,
)
from src.edgar.fetch import (
    DEFAULT_FORMS,
    DEFAULT_QUERIES,
    SPECIAL_DIV_FORMS,
    SPECIAL_DIV_QUERIES,
    SPIN_OFF_FORMS,
    SPIN_OFF_QUERIES,
    cik_to_ticker,
    efts_search,
    fetch_filing_text,
)
from src.edgar.keys import (
    article_key,
    special_dividend_key,
    spin_off_key,
    split_key,
)
from src.edgar.market_calendar import presplit_deadline_text

# Phase 5b: SIGNAL_TYPE added as the 12th column. Apps Script and
# any consumers reading older sheets default to ROUND_UP_REVERSE in
# parse_values when the header is absent — fully backward-compatible.
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
    "SIGNAL_TYPE",
)
_LOW_CONF = 0.50
# Spin-offs + special-divs trip the round-up alert gate; they need
# their own minimum confidence (set higher than reverse splits
# because false-positive cost is greater — operator can't tell at
# a glance that a special-div trade is real).
_NEW_TYPE_MIN_CONF = 0.75


class Play(NamedTuple):
    """A classified play ready for the GUI_QUEUE.

    Carries the originating signal type so plan_signals (Phase 7) can
    gate execution differently per type. ``ratio`` doubles as a
    free-form descriptor for new types (distribution ratio for
    spin-offs, dollar amount for special-divs).
    """

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
    signal_type: str = SIGNAL_TYPE_ROUND_UP_REVERSE


def _classify_hit(text: str, title: str) -> tuple[str, float, str]:
    """Best policy from filing text, falling back to the title."""
    fp = parse_fractional_policy(text)
    if fp.policy == "UNSPECIFIED" or fp.conf < _LOW_CONF:
        alt = parse_fractional_policy(title)
        if alt.policy != "UNSPECIFIED" and alt.conf > fp.conf:
            fp = alt
    return fp.policy, fp.conf, fp.evidence


def discover(  # noqa: PLR0913
    *,
    window_days: int = 14,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    enrich: bool = True,
    include_spin_off: bool = True,
    include_special_div: bool = True,
) -> list[Play]:
    """Search EDGAR and return alert-worthy, de-duplicated plays.

    Phase 5b: fans out across (queries x forms) for THREE signal
    types — reverse-split (default), spin-off, special-dividend.
    Each type has its own EFTS query/form set in fetch.py and its
    own dedupe key prefix so a reverse-split and a same-day
    spin-off for the same ticker never collide.
    """
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=window_days)).isoformat()
    end = today.isoformat()

    seen_acc: set[str] = set()
    seen_econ: set[str] = set()
    plays: list[Play] = []

    plays.extend(_discover_reverse_splits(
        queries=queries, forms=forms, enrich=enrich,
        start=start, end=end, seen_acc=seen_acc, seen_econ=seen_econ,
    ))
    if include_spin_off:
        plays.extend(_discover_spin_offs(
            enrich=enrich, start=start, end=end,
            seen_acc=seen_acc, seen_econ=seen_econ,
        ))
    if include_special_div:
        plays.extend(_discover_special_dividends(
            enrich=enrich, start=start, end=end,
            seen_acc=seen_acc, seen_econ=seen_econ,
        ))
    return plays


def _discover_reverse_splits(  # noqa: PLR0913
    *,
    queries: tuple[str, ...],
    forms: tuple[str, ...],
    enrich: bool,
    start: str,
    end: str,
    seen_acc: set[str],
    seen_econ: set[str],
) -> list[Play]:
    out: list[Play] = []
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
            if sk and sk in seen_econ:
                continue
            if sk:
                seen_econ.add(sk)
            out.append(
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
                    signal_type=SIGNAL_TYPE_ROUND_UP_REVERSE,
                ),
            )
    return out


def _discover_spin_offs(
    *,
    enrich: bool,
    start: str,
    end: str,
    seen_acc: set[str],
    seen_econ: set[str],
) -> list[Play]:
    out: list[Play] = []
    for q in SPIN_OFF_QUERIES:
        for hit in efts_search(q, start, end, SPIN_OFF_FORMS):
            if hit.accession in seen_acc:
                continue
            seen_acc.add(hit.accession)

            body = fetch_filing_text(hit.link) if enrich else ""
            text = body or hit.title
            r = parse_spin_off(text)
            if not r.matched or r.confidence < _NEW_TYPE_MIN_CONF:
                continue

            ticker = (hit.ticker or cik_to_ticker(hit.cik) or "").upper()
            if not ticker:
                continue
            sk = spin_off_key(ticker, r.record_date, r.distribution_ratio)
            if sk and sk in seen_econ:
                continue
            if sk:
                seen_econ.add(sk)
            out.append(
                Play(
                    ticker=ticker,
                    ratio=r.distribution_ratio,
                    effective_date=r.record_date,
                    fractional_policy="",
                    confidence=round(r.confidence, 2),
                    expectation="SPIN_OFF",
                    source="SEC_EFTS",
                    key=article_key(hit.link, hit.title),
                    split_key=sk,
                    link=hit.link,
                    signal_type=SIGNAL_TYPE_SPIN_OFF,
                ),
            )
    return out


def _discover_special_dividends(
    *,
    enrich: bool,
    start: str,
    end: str,
    seen_acc: set[str],
    seen_econ: set[str],
) -> list[Play]:
    out: list[Play] = []
    for q in SPECIAL_DIV_QUERIES:
        for hit in efts_search(q, start, end, SPECIAL_DIV_FORMS):
            if hit.accession in seen_acc:
                continue
            seen_acc.add(hit.accession)

            body = fetch_filing_text(hit.link) if enrich else ""
            text = body or hit.title
            r = parse_special_dividend(text)
            if not r.matched or r.confidence < _NEW_TYPE_MIN_CONF:
                continue

            ticker = (hit.ticker or cik_to_ticker(hit.cik) or "").upper()
            if not ticker:
                continue
            primary_date = r.record_date or r.ex_date or r.payment_date
            sk = special_dividend_key(ticker, primary_date, r.amount_per_share)
            if sk and sk in seen_econ:
                continue
            if sk:
                seen_econ.add(sk)
            # ``ratio`` carries the $ amount per share so the GUI can
            # surface it without an extra column. Format conservatively.
            amount_str = (
                f"${r.amount_per_share:.4f}".rstrip("0").rstrip(".")
                if r.amount_per_share else ""
            )
            out.append(
                Play(
                    ticker=ticker,
                    ratio=amount_str,
                    effective_date=primary_date,
                    fractional_policy="",
                    confidence=round(r.confidence, 2),
                    expectation="SPECIAL_DIV",
                    source="SEC_EFTS",
                    key=article_key(hit.link, hit.title),
                    split_key=sk,
                    link=hit.link,
                    signal_type=SIGNAL_TYPE_SPECIAL_DIV,
                ),
            )
    return out


def to_gui_rows(plays: list[Play]) -> list[list[object]]:
    """Render plays as GUI_QUEUE rows (matches writeGuiQueue_ exactly).

    Backward-compat: legacy 11-column sheets still parse correctly
    because :func:`src.gui.core.sheets.parse_values` defaults
    SIGNAL_TYPE to ROUND_UP_REVERSE when the header is absent.
    """
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
            p.signal_type,
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
