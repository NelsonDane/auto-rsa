"""Cheap, dependency-free ticker format validation.

Catches typos (case, spaces, stray punctuation, junk) *before* a run so
slow browser-broker logins aren't wasted on a bad symbol. This is a
format check only — it intentionally does not verify a symbol exists
(that would need a market-data dependency, deferred).

Permissive on purpose: RSA plays are often 5-letter OTC/penny tickers,
and class/preferred shares use a ``.``/``-`` suffix (BRK.B, RDS-A).
"""

from __future__ import annotations

import re

# 1-5 letters, optional single class suffix after '.' or '-' (1-3 letters).
_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,3})?$")


def normalize_and_validate(raw: str) -> tuple[list[str], list[str]]:
    """Split a comma list into (valid_upper, invalid_as_typed).

    Symbols are upper-cased and stripped before checking, so "aapl "
    becomes "AAPL" and is valid. Order is preserved; duplicates are
    de-duplicated in the valid list.
    """
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        original = token.strip()
        if not original:
            continue
        symbol = original.upper()
        if _TICKER_RE.match(symbol):
            if symbol not in seen:
                seen.add(symbol)
                valid.append(symbol)
        else:
            invalid.append(original)
    return valid, invalid
