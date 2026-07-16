"""Reconcile the execution ledger against a real holdings snapshot.

Answers the operator's recurring question — *did the order actually go
through?* — by cross-checking what the ledger says was bought against
what the broker actually holds. Two silent failures matter:

* MISSING  — the ledger says a buy EXECUTED, holdings are fresh, but the
  share is NOT in the account. The order likely never reached the broker
  even though the run reported success.
* NEEDS_REVIEW resolution — an ambiguous order (session broke mid-place):
  if the share is now held it probably went through; if not, it probably
  didn't. This turns a blocking NEEDS_REVIEW row into an actionable call.

Matching is at broker+ticker granularity on purpose: broker account
identifiers are inconsistent (full numbers vs ``****1234`` masks), so a
per-account match produces false alarms. "Held anywhere at this broker"
is the reliable signal for "did this buy land". Pure logic — no I/O — so
it's fully unit-testable; the GUI passes in the ledger rows + snapshot.
"""

from __future__ import annotations

import contextlib
import datetime
from typing import NamedTuple

from src import ledger

# Verdicts, ordered worst-first for display.
MISSING = "missing"
REVIEW_MISSED = "review_missed"
REVIEW_FILLED = "review_filled"
STALE = "stale"
UNVERIFIABLE = "unverifiable"
ORPHAN = "orphan"
OK = "ok"

_ORDER = {
    MISSING: 0,
    REVIEW_MISSED: 1,
    REVIEW_FILLED: 2,
    STALE: 3,
    UNVERIFIABLE: 4,
    ORPHAN: 5,
    OK: 6,
}

_ICON = {
    MISSING: "🔴",
    REVIEW_MISSED: "🟠",
    REVIEW_FILLED: "🟢",
    STALE: "🟡",
    UNVERIFIABLE: "⚪",
    ORPHAN: "🔵",
    OK: "🟢",
}

_LABEL = {
    MISSING: "Possible silent failure",
    REVIEW_MISSED: "Review — likely NOT bought",
    REVIEW_FILLED: "Review — likely bought",
    STALE: "Stale holdings",
    UNVERIFIABLE: "Not verifiable",
    ORPHAN: "Unexpected holding",
    OK: "Confirmed",
}


class Finding(NamedTuple):
    """One reconciliation result."""

    verdict: str
    broker: str
    account: str
    ticker: str
    status: str
    note: str

    @property
    def icon(self) -> str:
        """Traffic-light emoji for the verdict."""
        return _ICON.get(self.verdict, "•")

    @property
    def label(self) -> str:
        """Human label for the verdict."""
        return _LABEL.get(self.verdict, self.verdict)


def _parse(ts: object) -> datetime.datetime | None:
    with contextlib.suppress(Exception):
        return datetime.datetime.fromisoformat(str(ts))
    return None


def reconcile(
    ledger_rows: list[dict],
    positions: list[dict],
    captured_at: dict[str, str],
) -> list[Finding]:
    """Compare ledger buy rows against held positions. Worst findings first."""
    held: dict[str, set[str]] = {}
    for p in positions:
        broker = str(p.get("broker", "")).lower()
        stock = str(p.get("stock", "")).upper()
        if broker and stock:
            held.setdefault(broker, set()).add(stock)

    findings: list[Finding] = []
    seen_pairs: set[tuple[str, str]] = set()

    for row in ledger_rows:
        if str(row.get("action", "")).lower() != "buy":
            continue
        status = str(row.get("status", ""))
        if status not in (ledger.STATUS_EXECUTED, ledger.STATUS_NEEDS_REVIEW):
            continue
        broker = str(row.get("broker", "")).lower()
        ticker = str(row.get("ticker", "")).upper()
        account = str(row.get("sub_account", ""))
        seen_pairs.add((broker, ticker))

        cap = captured_at.get(broker)
        cap_dt = _parse(cap)
        row_dt = _parse(row.get("updated_at"))
        held_here = ticker in held.get(broker, set())

        if cap is None:
            verdict, note = (
                UNVERIFIABLE,
                "No holdings captured for this broker — pull holdings to verify.",
            )
        elif cap_dt is not None and row_dt is not None and cap_dt < row_dt:
            verdict, note = (
                STALE,
                "Holdings were captured before this order — pull fresh "
                "holdings to verify.",
            )
        elif status == ledger.STATUS_EXECUTED:
            verdict, note = (
                (OK, "Confirmed — the share is held.")
                if held_here
                else (
                    MISSING,
                    "Ledger says EXECUTED but the share is NOT in the "
                    "account — verify at the broker; it may not have gone "
                    "through.",
                )
            )
        else:  # NEEDS_REVIEW
            verdict, note = (
                (
                    REVIEW_FILLED,
                    "Ambiguous order — the share IS in the account, so it "
                    "likely went through. Reset the row if confirmed.",
                )
                if held_here
                else (
                    REVIEW_MISSED,
                    "Ambiguous order — the share is NOT in the account, so "
                    "it likely did not go through.",
                )
            )
        findings.append(Finding(verdict, broker, account, ticker, status, note))

    # Positions held with no matching buy row — bought elsewhere, or a fill
    # the ledger never recorded.
    for broker, tickers in held.items():
        for ticker in sorted(tickers):
            if (broker, ticker) not in seen_pairs:
                findings.append(
                    Finding(
                        ORPHAN, broker, "", ticker, "-",
                        "Held, but no matching buy in the ledger (bought "
                        "outside the tool, or a fill the ledger missed).",
                    ),
                )

    findings.sort(key=lambda f: _ORDER.get(f.verdict, 9))
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    """Count findings by verdict."""
    out: dict[str, int] = {}
    for f in findings:
        out[f.verdict] = out.get(f.verdict, 0) + 1
    return out
