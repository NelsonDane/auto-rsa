"""Dedupe keys — ports makeKey_ / makeAnnouncementSplitKey_.

``article_key`` is the per-source row identity (SHA-256 of link+title,
matches the Apps Script so the two producers don't double-queue the
same article into GUI_QUEUE).

``split_key`` is the **economic identity** of a play
(ticker|ratio|effective|policy). It's producer-agnostic, so the local
ledger keys idempotency on it as the safety net: the same real split
seen via StockTitan and via EDGAR collapses to one play and cannot be
bought twice.
"""

from __future__ import annotations

import base64
import hashlib
import re

from src.edgar.text import strip_html

_STOCK_NEWS_SUFFIX = re.compile(r"\s*\|\s*[A-Z]{1,6}\s+Stock News\s*$", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    x = strip_html(str(title or "")).strip()
    x = _STOCK_NEWS_SUFFIX.sub("", x)
    return _WS.sub(" ", x).strip()


def article_key(link: str, title: str) -> str:
    """SHA-256(link|normTitle), URL-safe base64 — matches the Apps Script."""
    base = f"{link or ''}|{_normalize_title(title)}"
    digest = hashlib.sha256(base.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def split_key(
    ticker: str,
    ratio: str,
    effective_date: str,
    fractional_policy: str,
) -> str:
    """Producer-agnostic economic identity, or '' if too sparse to trust."""
    t = str(ticker or "").strip().upper()
    if not t:
        return ""
    ratio_n = re.sub(r"\s+", "", str(ratio or "")).upper()
    eff_n = _WS.sub(" ", str(effective_date or "")).strip().upper()
    if not ratio_n and not eff_n:
        return ""
    frac = str(fractional_policy or "").strip().upper()
    return f"{t}|{ratio_n}|{eff_n}|{frac}"
