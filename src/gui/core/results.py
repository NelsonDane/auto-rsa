"""Conservative, status-only grouping of engine output.

Deliberately does NOT interpret or assert order outcomes. It only
filters the broker's own status lines and buckets them under the broker
they appear with, so a real-money result is never misrepresented by a
parser. Broker attribution is best-effort (word-boundary token match to
avoid e.g. "chase" matching "purchase").
"""

from __future__ import annotations

import re

from src.gui.core.brokers_meta import SUPPORTED_BROKERS

STATUS_MARKERS = (
    "error",
    "fail",
    "unsuccessful",
    "success",
    "complete",
    "skipping",
    "not found",
    "logged in",
    "logging in",
    "total value",
    "combined total",
    "dry:",
    "would've been",
)

_GENERAL = "General"


def _broker_patterns() -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for meta in SUPPORTED_BROKERS:
        toks = {
            meta.display_name.lower(),
            meta.key.lower(),
            meta.env_var.lower(),
            meta.display_name.replace(" ", "").lower(),
        }
        pat = re.compile(
            r"\b(?:" + "|".join(re.escape(t) for t in sorted(toks) if t) + r")\b",
        )
        out.append((meta.display_name, pat))
    return out


def status_lines(log: str) -> list[str]:
    """Verbatim lines that contain a status marker (a filter, not analysis)."""
    return [
        ln for ln in log.splitlines() if any(m in ln.lower() for m in STATUS_MARKERS)
    ]


def group_by_broker(log: str) -> dict[str, list[str]]:
    """Bucket verbatim status lines under the broker last referenced.

    Returns an insertion-ordered dict {broker_display_name: [lines]}.
    Lines before any broker is mentioned go under "General". Never
    asserts pass/fail — the lines are the brokers' own words.
    """
    patterns = _broker_patterns()
    groups: dict[str, list[str]] = {}
    current = _GENERAL
    for ln in log.splitlines():
        low = ln.lower()
        for disp, pat in patterns:
            if pat.search(low):
                current = disp
                break
        if any(m in low for m in STATUS_MARKERS):
            groups.setdefault(current, []).append(ln)
    return groups
