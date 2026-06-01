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


def spin_off_key(
    parent_ticker: str,
    record_date: str,
    distribution_ratio: str,
) -> str:
    """Economic identity for a spin-off — ``''`` if too sparse to trust.

    Includes the SIGNAL_TYPE prefix so a reverse-split and a spin-off
    with the same ticker / date never collide in the cross-feed ledger.
    """
    t = str(parent_ticker or "").strip().upper()
    if not t:
        return ""
    rd = _WS.sub(" ", str(record_date or "")).strip().upper()
    dr = re.sub(r"\s+", "", str(distribution_ratio or "")).upper()
    if not rd and not dr:
        return ""
    return f"SPIN_OFF|{t}|{rd}|{dr}"


def special_dividend_key(
    ticker: str,
    record_date: str,
    amount_per_share: float | str,
) -> str:
    """Economic identity for a special dividend — ``''`` if too sparse."""
    t = str(ticker or "").strip().upper()
    if not t:
        return ""
    rd = _WS.sub(" ", str(record_date or "")).strip().upper()
    try:
        amt = float(amount_per_share or 0)
    except (TypeError, ValueError):
        amt = 0.0
    if not rd and amt == 0.0:
        return ""
    return f"SPECIAL_DIV|{t}|{rd}|{amt:.4f}"
