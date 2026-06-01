"""Deterministic reverse-split classifier — 1:1 port of the Apps Script.

The ordered cascade in :func:`parse_fractional_policy` is load-bearing:
cash-in-lieu is tested before round-up so a filing that says both
("no fractional shares; cash will be paid in lieu ... otherwise rounded
up") is correctly classified CASH_IN_LIEU (not a tradable play). Do not
reorder without updating the corpus tests.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Only ROUND_UP at/above this confidence is auto-trade eligible; the
# alert gate uses the same floor (CONFIG.FRACTIONAL_MIN_CONF in the .gs).
FRACTIONAL_MIN_CONF = 0.60

POLICY_CASH_IN_LIEU = "CASH_IN_LIEU"
POLICY_AGGREGATED_SOLD_CASH = "AGGREGATED_SOLD_CASH"
POLICY_ROUND_UP = "ROUND_UP"
POLICY_ROUND_DOWN = "ROUND_DOWN"
POLICY_NEAREST_WHOLE = "NEAREST_WHOLE"
POLICY_NO_FRACTIONAL_SHARES = "NO_FRACTIONAL_SHARES"
POLICY_UNSPECIFIED = "UNSPECIFIED"

_I = re.IGNORECASE

_CASH_IN_LIEU = re.compile(
    r"(cash\s+in\s+lieu|cash\s+in-lieu|cash\s+payment\s+in\s+lieu"
    r"|paid\s+in\s+cash\s+in\s+lieu|receive\s+cash\s+in\s+lieu"
    r"|fractional\s+shares?\s+(?:will\s+be\s+)?paid\s+in\s+cash)",
    _I,
)
_AGG_SOLD_CASH = re.compile(
    r"(fractional\s+entitlements?\s+will\s+be\s+aggregated\s+and\s+sold"
    r"|aggregated\s+and\s+sold[\s\S]{0,120}cash"
    r"|net\s+proceeds[\s\S]{0,120}distributed[\s\S]{0,40}cash"
    r"|sold[\s\S]{0,120}distributed[\s\S]{0,40}cash)",
    _I,
)
_ROUND_UP_STRONG = re.compile(
    r"(shareholders?\s+will\s+be\s+issued\s+one\s+whole\s+(?:common\s+)?share"
    r"|shareholders?\s+will\s+receive\s+one\s+(?:whole|full)\s+(?:common\s+)?"
    r"share(?:\s+in\s+lieu\s+of\s+fractions?)?"
    r"|will\s+receive\s+one\s+(?:whole|full)\s+(?:common\s+)?share"
    r"(?:\s+in\s+lieu\s+of\s+fractions?)?"
    r"|one\s+(?:whole|full)\s+(?:common\s+)?share\s+in\s+lieu\s+of\s+fractions?"
    r"|will\s+be\s+issued\s+one\s+whole\s+(?:common\s+)?share"
    r"|issued\s+one\s+whole\s+(?:common\s+)?share"
    r"|in\s+exchange\s+for\s+any\s+fractional\s+interest"
    r"|in\s+lieu\s+of\s+any\s+fractional(?:\s+share|\s+interest)?"
    r"|fractional\s+entitlements?\s+will\s+be\s+rounded\s+up"
    r"|rounded\s+up\s+to\s+the\s+nearest\s+whole\s+share"
    r"|(?:round|rounded)\s+up)",
    _I,
)
_ROUND_DOWN = re.compile(
    r"(rounded\s+down\s+to\s+the\s+nearest\s+whole\s+share"
    r"|fractional\s+entitlements?\s+will\s+be\s+rounded\s+down"
    r"|fractional\s+shares?\s+will\s+be\s+"
    r"(?:cancelled|canceled|discarded|eliminated))",
    _I,
)
_NO_FRACTION_ISSUED = re.compile(
    r"(no\s+fractional\s+shares?\s+will\s+be\s+issued"
    r"|will\s+not\s+issue\s+fractional\s+shares?"
    r"|no\s+fractional\s+shares?\s+will\s+be\s+distributed)",
    _I,
)
_NEAREST_WHOLE = re.compile(
    r"(rounded\s+to\s+the\s+nearest\s+whole\s+(?:share|number\s+of\s+shares)"
    r"|rounded\s+to\s+whole\s+shares)",
    _I,
)
_CASH_LANGUAGE = re.compile(
    r"(cash\s+in\s+lieu|paid\s+in\s+cash|cash\s+payment|settled\s+in\s+cash"
    r"|net\s+proceeds|distributed\s+in\s+cash)",
    _I,
)


class FractionalPolicy(NamedTuple):
    """Classified fractional-share treatment + confidence + evidence."""

    policy: str
    conf: float
    evidence: str


def _best_evidence(text: str, regex: re.Pattern[str], max_len: int = 520) -> str:
    s = text or ""
    m = regex.search(s)
    if not m:
        return ""
    idx = s.lower().find(m.group(0).lower())
    idx = max(0, idx)
    start = max(0, idx - 90)
    return re.sub(r"\s+", " ", s[start:start + max_len]).strip()


def parse_fractional_policy(text: str) -> FractionalPolicy:  # noqa: PLR0911
    """Classify the fractional-share treatment. Order is intentional."""
    s = text or ""
    if _CASH_IN_LIEU.search(s):
        return FractionalPolicy(POLICY_CASH_IN_LIEU, 0.96, _best_evidence(s, _CASH_IN_LIEU))
    if _AGG_SOLD_CASH.search(s):
        return FractionalPolicy(
            POLICY_AGGREGATED_SOLD_CASH, 0.95, _best_evidence(s, _AGG_SOLD_CASH),
        )
    if _ROUND_UP_STRONG.search(s):
        return FractionalPolicy(POLICY_ROUND_UP, 0.93, _best_evidence(s, _ROUND_UP_STRONG))
    if _ROUND_DOWN.search(s):
        return FractionalPolicy(POLICY_ROUND_DOWN, 0.92, _best_evidence(s, _ROUND_DOWN))
    if _NO_FRACTION_ISSUED.search(s) and _NEAREST_WHOLE.search(s):
        return FractionalPolicy(POLICY_NEAREST_WHOLE, 0.70, _best_evidence(s, _NEAREST_WHOLE))
    if _NO_FRACTION_ISSUED.search(s):
        return FractionalPolicy(
            POLICY_NO_FRACTIONAL_SHARES, 0.60, _best_evidence(s, _NO_FRACTION_ISSUED),
        )
    if _NEAREST_WHOLE.search(s):
        return FractionalPolicy(POLICY_NEAREST_WHOLE, 0.70, _best_evidence(s, _NEAREST_WHOLE))
    return FractionalPolicy(POLICY_UNSPECIFIED, 0.20, "")


# --- reverse split / ratio --------------------------------------------

_RATIO_NUM = (
    re.compile(r"1\s*[- ]?for\s*[- ]?(\d+)", _I),
    re.compile(r"1\s*[- ]?to\s*(\d+)", _I),
    re.compile(r"1\s*:\s*(\d+)", _I),
)
_REV_RATIO = (
    re.compile(r"\b1\s*[-\s]?for[-\s]?(\d+)\b", _I),
    re.compile(r"\b1\s*:\s*(\d{1,5})\b"),
    re.compile(r"\b1\s*[-\s]?to[-\s]?(\d+)\b", _I),
)
_MIN_REV, _MAX_REV = 2, 100000
_COMPLIANCE = re.compile(
    r"nasdaq.*compliance|minimum bid|bid price|listing compliance"
    r"|price deficiency",
    _I,
)


def ratio_to_number(ratio: str) -> int | None:
    """'1-for-40' / '1:40' / '1 to 40' -> 40."""
    for rx in _RATIO_NUM:
        m = rx.search(str(ratio or ""))
        if m:
            return int(m.group(1))
    return None


class ReverseSplit(NamedTuple):
    """Extracted reverse-split ratio, effective date, and reason."""

    ratio: str | None
    effective_date: str | None
    reason: str | None


_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?"
    r"|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_RES = (
    re.compile(
        rf"effective(?:\s+(?:on|as of))?\s+(?:on or about\s+)?"
        rf"({_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",
        _I,
    ),
    re.compile(
        rf"(?:become|becomes|will be|is expected to be|is scheduled to be)"
        rf"\s+effective\s+(?:on\s+)?(?:on or about\s+)?"
        rf"({_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",
        _I,
    ),
    re.compile(
        rf"effective\s+date\s+(?:of|is|will be)\s+"
        rf"({_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",
        _I,
    ),
    re.compile(
        rf"(?:close of business on|as of the close of business on)\s+"
        rf"({_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",
        _I,
    ),
    re.compile(r"effective[^.]{0,40}\b(\d{4}-\d{2}-\d{2})\b", _I),
    re.compile(r"effective[^.]{0,40}\b(\d{1,2}/\d{1,2}/\d{4})\b", _I),
)
_ORDINAL = re.compile(r"(st|nd|rd|th)", _I)


def parse_reverse_split(text: str) -> ReverseSplit:
    """Extract a REVERSE ratio (1-for-N, N>=2) + effective date + reason."""
    s = str(text or "")
    ratio = None
    for rx in _REV_RATIO:
        m = rx.search(s)
        if m:
            n = int(m.group(1))
            if _MIN_REV <= n <= _MAX_REV:
                ratio = f"1-for-{n}"
            break
    eff = None
    for rx in _DATE_RES:
        m = rx.search(s)
        if m:
            eff = _ORDINAL.sub("", m.group(1))
            break
    reason = "Compliance" if _COMPLIANCE.search(s) else None
    return ReverseSplit(ratio, eff, reason)


def derive_fractional_expectation(
    policy: str, *, is_reverse_split: bool, ratio: str, evidence_text: str,
) -> str:
    """ROUND_UP_CONFIRMED / CASH_CONFIRMED / ... / ROUND_UP_LIKELY / UNKNOWN."""
    p = str(policy or "").upper()
    if p == POLICY_ROUND_UP:
        return "ROUND_UP_CONFIRMED"
    if p in {POLICY_CASH_IN_LIEU, POLICY_AGGREGATED_SOLD_CASH}:
        return "CASH_CONFIRMED"
    if p == POLICY_ROUND_DOWN:
        return "ROUND_DOWN_CONFIRMED"
    ratio_num = ratio_to_number(ratio)
    if (
        p == POLICY_UNSPECIFIED
        and is_reverse_split
        and ratio_num is not None
        and ratio_num >= 10  # noqa: PLR2004
        and not _CASH_LANGUAGE.search(evidence_text or "")
    ):
        return "ROUND_UP_LIKELY"
    return "UNKNOWN"


# --- gating ------------------------------------------------------------

_ALERT_POLICIES = frozenset(
    {POLICY_ROUND_UP, POLICY_ROUND_DOWN, POLICY_AGGREGATED_SOLD_CASH},
)


def is_round_up_fractional(policy: str, conf: float) -> bool:
    """Auto-trade gate: only a confident ROUND_UP is buy-eligible."""
    return str(policy or "").upper() == POLICY_ROUND_UP and float(conf or 0) >= FRACTIONAL_MIN_CONF


def should_alert_for_rsa(policy: str, conf: float) -> bool:
    """Alert gate (wider than the buy gate, mirrors the .gs)."""
    return (
        str(policy or "").upper() in _ALERT_POLICIES
        and float(conf or 0) >= FRACTIONAL_MIN_CONF
    )


# --- ratio bucket / EV -------------------------------------------------

_BUCKET_EV = {
    "MINI": 2.50,
    "LOW": 4.00,
    "MID": 6.50,
    "HIGH": 9.00,
    "MEGA": 12.00,
}


def classify_ratio_bucket(ratio_num: float | None) -> str:  # noqa: PLR0911
    """Map a reverse-split N to an EV bucket (MINI/LOW/MID/HIGH/MEGA)."""
    n = float(ratio_num) if ratio_num is not None else 0.0
    if n <= 1:
        return "UNKNOWN"
    if n >= 100:  # noqa: PLR2004
        return "MEGA"
    if n >= 50:  # noqa: PLR2004
        return "HIGH"
    if n >= 25:  # noqa: PLR2004
        return "MID"
    if n >= 10:  # noqa: PLR2004
        return "LOW"
    if n >= 2:  # noqa: PLR2004
        return "MINI"
    return "UNKNOWN"


def bucket_ev_usd(bucket: str) -> float:
    """Return the expected $ per 1-share position for a ratio bucket."""
    return _BUCKET_EV.get(str(bucket or "").upper(), 0.0)


# ---------------------------------------------------------------------------
# Signal-type detection (spin-offs + special dividends)
# ---------------------------------------------------------------------------
# These extend the EDGAR pipeline beyond reverse splits. Each returns a
# typed result with a confidence score; the producer cascades from
# reverse-split → special-div → spin-off (rarest last). Operator
# selected Spin-offs + Special dividends in the design discussion;
# forward splits are deferred (sentiment-only, no mechanical
# arbitrage). See the design doc for the full strategy rationale.

SIGNAL_TYPE_ROUND_UP_REVERSE = "ROUND_UP_REVERSE"
SIGNAL_TYPE_SPIN_OFF = "SPIN_OFF"
SIGNAL_TYPE_SPECIAL_DIV = "SPECIAL_DIV"

SIGNAL_TYPES = (
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPIN_OFF,
    SIGNAL_TYPE_SPECIAL_DIV,
)

# Phrases that strongly indicate the document is a spin-off announcement.
# We don't try to extract the spin-off ticker (often not assigned at
# announcement time); we capture record date and distribution-ratio
# evidence so the operator can validate downstream.
_SPIN_OFF_STRONG = re.compile(
    r"(spin-?off|spin\s+off"
    r"|separation\s+(?:of|into)\s+(?:two|a)\s+(?:separate|publicly[-\s]traded|independent)"
    r"|distribution\s+of\s+(?:one\s+share|shares?)\s+of\s+[A-Z][\w\s.]+\s+common\s+stock"
    r"|distribute\s+(?:all|substantially\s+all)\s+of\s+the\s+(?:outstanding\s+)?shares?"
    r")",
    _I,
)
_SPIN_OFF_SUPPORTING = re.compile(
    r"(record\s+date|distribution\s+date|ex-?distribution"
    r"|share\s+distribution\s+ratio"
    r"|holders?\s+of\s+record"
    r"|board\s+of\s+directors?\s+(?:authoriz|approv))",
    _I,
)
_SPIN_OFF_DIST_RATIO = re.compile(
    # Tolerates words between "common stock" and "for every" (e.g.
    # "common stock distributed for every", "common stock will be
    # distributed for every"). Bounded to 40 chars + non-period so
    # we don't match across sentences.
    r"(?:one|1)\s+share\s+of\s+(?:[A-Z][\w\s.]+\s+)?common\s+stock"
    r"[^.]{0,40}?for\s+every\s+(\d+)\s+shares?",
    _I,
)
_SPIN_OFF_RECORD_DATE = re.compile(
    r"record\s+date[^.]{0,80}?"
    r"(\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})",
    _I,
)

# Special-dividend announcements live mostly in 8-K Item 8.01.
# The high-value extraction targets: amount per share, ex-date,
# record date, payment date. We anchor on "special" + "dividend"
# so a normal quarterly dividend isn't mis-classified.
_SPECIAL_DIV_STRONG = re.compile(
    r"(special\s+(?:cash\s+)?dividend"
    r"|extraordinary\s+(?:cash\s+)?dividend"
    r"|one-?time\s+(?:cash\s+)?dividend"
    r"|special\s+(?:cash\s+)?distribution)",
    _I,
)
# Quarterly / regular dividends that we MUST NOT classify as special.
_REGULAR_DIV = re.compile(
    r"(quarterly\s+(?:cash\s+)?dividend|regular\s+(?:cash\s+)?dividend"
    r"|increase[ds]?\s+(?:its\s+)?(?:quarterly\s+)?dividend)",
    _I,
)
_SPECIAL_DIV_AMOUNT = re.compile(
    r"(?:special\s+(?:cash\s+)?dividend|extraordinary\s+(?:cash\s+)?dividend"
    r"|one-?time\s+(?:cash\s+)?dividend)[^$]{0,80}?"
    r"\$\s?(\d+(?:\.\d{1,4})?)\s*per\s+share",
    _I,
)
_SPECIAL_DIV_DATE = re.compile(
    # SEC filings often phrase "to stockholders of record as of <date>"
    # rather than "record date <date>" — accept both. Same for
    # "payable <date>" vs "payment date <date>".
    r"(ex-?dividend\s+date|record\s+date|of\s+record(?:\s+as\s+of)?"
    r"|payable\s+(?:on)?|payment\s+date)[^.]{0,80}?"
    r"(\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})",
    _I,
)


class SpinOffResult(NamedTuple):
    """Output of :func:`parse_spin_off`."""

    matched: bool
    confidence: float
    record_date: str  # raw string; downstream parses to date if needed
    distribution_ratio: str  # e.g. "1-for-3" or "" if not detected
    evidence: str  # snippet for operator review


class SpecialDividendResult(NamedTuple):
    """Output of :func:`parse_special_dividend`."""

    matched: bool
    confidence: float
    amount_per_share: float  # 0.0 if not extracted
    ex_date: str
    record_date: str
    payment_date: str
    evidence: str


def _snippet(text: str, match: re.Match[str], window: int = 80) -> str:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return re.sub(r"\s+", " ", text[start:end]).strip()


_EMPTY_SPIN_OFF = SpinOffResult(
    matched=False, confidence=0.0, record_date="",
    distribution_ratio="", evidence="",
)
_EMPTY_SPECIAL_DIV = SpecialDividendResult(
    matched=False, confidence=0.0, amount_per_share=0.0,
    ex_date="", record_date="", payment_date="", evidence="",
)


def parse_spin_off(text: str) -> SpinOffResult:
    """Detect a spin-off announcement and extract record date + ratio.

    The classifier is conservative: it requires a STRONG trigger
    phrase AND at least one supporting term (record/distribution
    date, holders of record, board authorization). False positives
    are more costly here than misses — the operator wants signals
    they can act on.
    """
    s = str(text or "")
    if not s.strip():
        return _EMPTY_SPIN_OFF

    strong = _SPIN_OFF_STRONG.search(s)
    if not strong:
        return _EMPTY_SPIN_OFF
    supporting = _SPIN_OFF_SUPPORTING.search(s)
    if not supporting:
        # Strong phrase without supporting context (e.g. someone
        # mentioning a future possibility) — low confidence, no signal.
        return SpinOffResult(
            matched=False, confidence=0.20,
            record_date="", distribution_ratio="",
            evidence=_snippet(s, strong),
        )

    conf = 0.65
    dist_match = _SPIN_OFF_DIST_RATIO.search(s)
    distribution_ratio = ""
    if dist_match:
        distribution_ratio = f"1-for-{dist_match.group(1)}"
        conf += 0.15

    record_date = ""
    rd_match = _SPIN_OFF_RECORD_DATE.search(s)
    if rd_match:
        record_date = rd_match.group(1)
        conf += 0.10

    return SpinOffResult(
        matched=True,
        confidence=min(conf, 0.95),
        record_date=record_date,
        distribution_ratio=distribution_ratio,
        evidence=_snippet(s, strong),
    )


def parse_special_dividend(text: str) -> SpecialDividendResult:  # noqa: C901
    """Detect a special dividend and extract amount + dates.

    Requires the strong phrase AND must NOT match the regular-dividend
    guard within the same document. The most common false positive is
    "increased its quarterly dividend" being read as "dividend" alone.
    """
    s = str(text or "")
    if not s.strip():
        return _EMPTY_SPECIAL_DIV

    strong = _SPECIAL_DIV_STRONG.search(s)
    if not strong:
        return _EMPTY_SPECIAL_DIV

    # Don't fight against a clearly-regular dividend phrasing in the
    # same document. (We allow it iff the special phrase is the
    # PRIMARY one; a doc that says "special dividend" once and
    # "quarterly dividend" three times is probably a regular div.)
    if _REGULAR_DIV.search(s):
        # Require a stronger signal: an amount + date must be present.
        amount_match = _SPECIAL_DIV_AMOUNT.search(s)
        if not amount_match:
            return SpecialDividendResult(
                matched=False, confidence=0.25,
                amount_per_share=0.0, ex_date="", record_date="",
                payment_date="", evidence=_snippet(s, strong),
            )

    conf = 0.70
    amount = 0.0
    amount_match = _SPECIAL_DIV_AMOUNT.search(s)
    if amount_match:
        try:
            amount = float(amount_match.group(1))
            conf += 0.15
        except ValueError:
            pass

    ex_date = record_date = payment_date = ""
    for label, value in _SPECIAL_DIV_DATE.findall(s):
        label_l = label.lower()
        if "ex" in label_l and not ex_date:
            ex_date = value
        elif "record" in label_l and not record_date:
            record_date = value
        elif ("payable" in label_l or "payment" in label_l) and not payment_date:
            payment_date = value
    if ex_date or record_date or payment_date:
        conf += 0.10

    return SpecialDividendResult(
        matched=True,
        confidence=min(conf, 0.95),
        amount_per_share=amount,
        ex_date=ex_date,
        record_date=record_date,
        payment_date=payment_date,
        evidence=_snippet(s, strong),
    )
