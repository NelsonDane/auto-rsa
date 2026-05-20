"""HTML/text cleanup — port of stripHtml_ / extractReadableTextFromHtml_."""

from __future__ import annotations

import re

_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_STYLE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
_WS = re.compile(r"\s+")
_BLOCK = re.compile(r"<(aside|nav|footer)[\s\S]*?</\1>", re.IGNORECASE)
_SIDEBAR = re.compile(
    r'<div[^>]+(?:class|id)="[^"]*'
    r"(?:sidebar|related|trending|popular|sponsored|advert|promo)"
    r'[^"]*"[\s\S]*?</div>',
    re.IGNORECASE,
)
_PR_TAIL = re.compile(
    r"\b(?:Fractional shares are portions of a whole share"
    r"|What are fractional shares\?)[\s\S]*$",
    re.IGNORECASE,
)


def strip_html(s: str) -> str:
    """Collapse HTML to plain whitespace-normalized text."""
    s = s or ""
    s = _SCRIPT.sub(" ", s)
    s = _STYLE.sub(" ", s)
    s = _TAG.sub(" ", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return _WS.sub(" ", s).strip()


def extract_readable_text(html: str) -> str:
    """Best-effort article body extraction (PR-Newswire dateline aware)."""
    s = html or ""
    s = _SCRIPT.sub(" ", s)
    s = _STYLE.sub(" ", s)
    s = _BLOCK.sub(" ", s)
    s = _SIDEBAR.sub(" ", s)
    full = strip_html(s)

    pr_idx = full.find("/PRNewswire/")
    if pr_idx >= 0:
        full = full[max(0, pr_idx - 80):].strip()
    return _PR_TAIL.sub("", full).strip()
