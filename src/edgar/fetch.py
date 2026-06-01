"""SEC EDGAR access — EFTS full-text search + filing/CIK lookups.

Port of the Apps Script SEC paths to Python ``requests``. SEC requires
a descriptive User-Agent with contact info and rate-limits at ~10
req/s; we send a UA and sleep between calls. Every call is best-effort:
network/parse failures return ``[]`` / ``None`` / ``""`` and never
raise, so one bad filing can't break a scrape run.

Forms widened (per design): 8-K, 424B*, DEF 14A, PRE 14A.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import NamedTuple

import requests

from src.edgar.text import extract_readable_text

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

DEFAULT_FORMS = ("8-K", "424B1", "424B3", "424B4", "424B5", "DEF 14A", "PRE 14A")
DEFAULT_QUERIES = ('"reverse stock split"', '"reverse split"')

# Phase 5: spin-off + special-dividend discovery use their own
# EFTS queries so the existing reverse-split pipeline stays
# focused. Special dividends most often land in 8-K item 8.01;
# spin-offs in 8-K + 10-12B + Form 10.
SPIN_OFF_QUERIES = ('"spin-off"', '"spinoff"', '"distribution of"')
SPIN_OFF_FORMS = ("8-K", "10-12B", "10-12B/A", "S-1", "S-4")
SPECIAL_DIV_QUERIES = (
    '"special cash dividend"',
    '"special dividend"',
    '"extraordinary dividend"',
)
SPECIAL_DIV_FORMS = ("8-K",)
_DEFAULT_UA = "AutoRSA reverse-split research (ralanleder@gmail.com)"
_SEC_SLEEP_S = 0.4
_HTTP_OK = 200
_FILING_MAX_CHARS = 20000


def _ua() -> str:
    return os.getenv("RSA_SEC_USER_AGENT", "").strip() or _DEFAULT_UA


def _headers(*, json: bool = False) -> dict[str, str]:
    return {
        "User-Agent": _ua(),
        "Accept": "application/json" if json else "text/html,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }


class Hit(NamedTuple):
    """One EFTS search hit (a filing)."""

    accession: str
    cik: str
    ticker: str | None
    form: str
    filing_date: str
    link: str
    title: str


def efts_search(  # noqa: PLR0914
    query: str,
    start_date: str,
    end_date: str,
    forms: tuple[str, ...] = DEFAULT_FORMS,
) -> list[Hit]:
    """Run one EFTS full-text query. Returns [] on any failure."""
    params = {
        "q": query,
        "forms": ",".join(forms),
        "startdt": start_date,
        "enddt": end_date,
    }
    time.sleep(_SEC_SLEEP_S)
    try:
        resp = requests.get(
            _EFTS_URL, params=params, headers=_headers(json=True), timeout=30,
        )
    except requests.RequestException:
        return []
    if resp.status_code != _HTTP_OK:
        return []
    try:
        hits = resp.json().get("hits", {}).get("hits", [])
    except ValueError:
        return []

    out: list[Hit] = []
    for h in hits:
        src = h.get("_source", {}) or {}
        hid = str(h.get("_id", ""))
        accession, _, filename = hid.partition(":")
        ciks = src.get("ciks") or []
        cik = str(ciks[0]).lstrip("0") if ciks else ""
        if not (cik and accession):
            continue
        display = (src.get("display_names") or [""])[0]
        ticker = None
        if "(" in display and ")" in display:
            seg = display[display.find("(") + 1:display.find(")")]
            if seg.isalpha() and 1 <= len(seg) <= 6:  # noqa: PLR2004
                ticker = seg.upper()
        acc_nodash = accession.replace("-", "")
        link = _ARCHIVES.format(
            cik=cik,
            acc=acc_nodash,
            doc=filename or f"{accession}-index.htm",
        )
        forms_src = src.get("file_type") or src.get("root_forms") or ""
        out.append(
            Hit(
                accession=accession,
                cik=cik,
                ticker=ticker,
                form=str(forms_src),
                filing_date=str(src.get("file_date", "")),
                link=link,
                title=str(display or "8-K"),
            ),
        )
    return out


@lru_cache(maxsize=4096)
def _cik_ticker_cached(cik10: str) -> str | None:
    url = _SUBMISSIONS_URL.format(cik10=cik10)
    time.sleep(_SEC_SLEEP_S)
    try:
        resp = requests.get(url, headers=_headers(json=True), timeout=30)
        if resp.status_code != _HTTP_OK:
            return None
        tickers = resp.json().get("tickers") or []
    except (requests.RequestException, ValueError):
        return None
    return str(tickers[0]).upper() if tickers else None


def cik_to_ticker(cik: str) -> str | None:
    """Resolve a CIK to its primary ticker (cached; zero-pad agnostic)."""
    c = str(cik or "").lstrip("0")
    if not c:
        return None
    return _cik_ticker_cached(c.zfill(10))


cik_to_ticker.cache_clear = _cik_ticker_cached.cache_clear  # type: ignore[attr-defined]


def fetch_filing_text(url: str) -> str:
    """Fetch a filing document and return readable text (capped)."""
    if not url:
        return ""
    time.sleep(_SEC_SLEEP_S)
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
    except requests.RequestException:
        return ""
    if resp.status_code != _HTTP_OK:
        return ""
    text = resp.text or ""
    if "<html" in text[:2000].lower():
        text = extract_readable_text(text)
    return text[:_FILING_MAX_CHARS]
