"""Locks the deterministic classifier behavior (1:1 with the Apps Script).

These assert the load-bearing invariants — especially that cash-in-lieu
beats round-up when both phrasings appear, since a false ROUND_UP would
trigger a real-money buy on a non-play.
"""

from src.edgar.classify import (
    bucket_ev_usd,
    classify_ratio_bucket,
    derive_fractional_expectation,
    is_round_up_fractional,
    parse_fractional_policy,
    parse_reverse_split,
    ratio_to_number,
    should_alert_for_rsa,
)
from src.edgar.keys import article_key, split_key
from src.edgar.text import strip_html

# Real snippets observed in the labeled corpus.
ROUND_UP_REAL = (
    "no fractional shares will be issued in connection with the reverse "
    "share split and all such fractional interests will be rounded up to "
    "the nearest whole number of Class A Ordinary Shares."
)
CASH_REAL = (
    "No fractional shares will be issued. Stockholders otherwise entitled "
    "to a fractional share will receive cash in lieu of fractional shares."
)


def test_round_up_variants():
    for txt in (
        ROUND_UP_REAL,
        "fractional shares will be rounded up to the nearest whole share",
        "shareholders will receive one whole share in lieu of fractions",
        "fractional entitlements will be rounded up",
    ):
        p = parse_fractional_policy(txt)
        assert p.policy == "ROUND_UP", txt
        assert p.conf == 0.93
        assert p.evidence


def test_effective_date_normalization_round_trip():
    from src.edgar.market_calendar import parse_effective_date

    cases = {
        # abbreviated month + trailing period used to lose the deadline
        "the split is effective on Jan. 5, 2026": "2026-01-05",
        # global ordinal strip used to eat the "st" in August -> "Augu"
        "the split is effective on August 5, 2026": "2026-08-05",
        # 4-letter "Sept" abbreviation
        "the split becomes effective on Sept. 30, 2026": "2026-09-30",
        # ordinal on the day number still stripped
        "effective on January 5th, 2026": "2026-01-05",
    }
    for text, want in cases.items():
        eff = parse_reverse_split(text).effective_date
        assert parse_effective_date(eff or "") is not None, (text, eff)
        assert parse_effective_date(eff or "").isoformat() == want, (text, eff)


def test_bare_rounded_up_no_longer_false_positives():
    # Regression: a bare "round(ed) up" with no fractional-share context
    # used to classify as ROUND_UP @ 0.93 and trigger a real-money buy.
    for txt in (
        "the proceeds were rounded up for accounting purposes",
        "the exercise price will be rounded up to the nearest cent",
        "the board approved a 1-for-10 reverse stock split; amounts were "
        "rounded up in the table above",
    ):
        assert parse_fractional_policy(txt).policy != "ROUND_UP", txt


def test_round_down_with_stray_round_up_is_not_a_buy():
    # A genuine round-DOWN filing that also says "rounded up" somewhere is
    # contradictory; it must NOT be classified as a buyable ROUND_UP.
    txt = (
        "fractional shares will be rounded down to the nearest whole "
        "share; in no event will any fractional share be rounded up."
    )
    assert parse_fractional_policy(txt).policy == "ROUND_DOWN"


def test_cash_beats_round_up_ordering():
    # Both phrasings present -> CASH must win (the money-safety invariant).
    both = (
        "No fractional shares will be issued; holders otherwise entitled "
        "to a fraction would be rounded up to the nearest whole share, "
        "provided that the Company will instead pay cash in lieu of "
        "fractional shares."
    )
    assert parse_fractional_policy(both).policy == "CASH_IN_LIEU"
    assert parse_fractional_policy(CASH_REAL).policy == "CASH_IN_LIEU"


def test_other_policies():
    assert parse_fractional_policy(
        "fractional shares will be rounded down to the nearest whole share",
    ).policy == "ROUND_DOWN"
    assert parse_fractional_policy(
        "fractional entitlements will be aggregated and sold with net "
        "proceeds distributed in cash",
    ).policy in ("AGGREGATED_SOLD_CASH", "CASH_IN_LIEU")
    assert parse_fractional_policy(
        "No fractional shares will be issued in the reverse split.",
    ).policy == "NO_FRACTIONAL_SHARES"
    assert parse_fractional_policy(
        "Holdings will be rounded to the nearest whole share.",
    ).policy == "NEAREST_WHOLE"
    p = parse_fractional_policy("The board approved a reverse stock split.")
    assert p.policy == "UNSPECIFIED" and p.conf == 0.20 and p.evidence == ""


def test_reverse_split_only_reverse_ratios():
    assert parse_reverse_split("a 1-for-40 reverse stock split").ratio == "1-for-40"
    assert parse_reverse_split("1:25 consolidation").ratio == "1-for-25"
    # Forward split must not produce a ratio (no false RSA buy).
    assert parse_reverse_split("a 2-for-1 forward split").ratio is None
    # 1-for-1 is below the reverse threshold.
    assert parse_reverse_split("1-for-1 housekeeping").ratio is None
    eff = parse_reverse_split(
        "The reverse split will become effective on March 3, 2026.",
    )
    assert eff.effective_date == "March 3, 2026"
    assert parse_reverse_split(
        "to regain Nasdaq listing compliance with the minimum bid price",
    ).reason == "Compliance"


def test_ratio_helpers_and_buckets():
    assert ratio_to_number("1-for-40") == 40
    assert ratio_to_number("1:7") == 7
    assert ratio_to_number("nonsense") is None
    assert classify_ratio_bucket(40) == "MID"
    assert classify_ratio_bucket(120) == "MEGA"
    assert classify_ratio_bucket(1) == "UNKNOWN"
    assert bucket_ev_usd("MID") == 6.50
    assert bucket_ev_usd("???") == 0.0


def test_expectation_and_gates():
    assert derive_fractional_expectation(
        "ROUND_UP", is_reverse_split=True, ratio="1-for-40", evidence_text="",
    ) == "ROUND_UP_CONFIRMED"
    assert derive_fractional_expectation(
        "CASH_IN_LIEU", is_reverse_split=True, ratio="1-for-5", evidence_text="",
    ) == "CASH_CONFIRMED"
    # Unspecified + big reverse ratio + no cash language -> likely round-up.
    assert derive_fractional_expectation(
        "UNSPECIFIED", is_reverse_split=True, ratio="1-for-30",
        evidence_text="no mention of money here",
    ) == "ROUND_UP_LIKELY"
    # ...but cash language kills the inference.
    assert derive_fractional_expectation(
        "UNSPECIFIED", is_reverse_split=True, ratio="1-for-30",
        evidence_text="cash in lieu will be paid",
    ) == "UNKNOWN"

    assert is_round_up_fractional("ROUND_UP", 0.93) is True
    assert is_round_up_fractional("ROUND_UP", 0.50) is False
    assert is_round_up_fractional("CASH_IN_LIEU", 0.99) is False
    assert should_alert_for_rsa("ROUND_DOWN", 0.92) is True
    assert should_alert_for_rsa("UNSPECIFIED", 0.99) is False


def test_keys():
    k1 = article_key(
        "https://x.com/a", "Acme does a thing | ACME Stock News",
    )
    k2 = article_key("https://x.com/a", "Acme does a thing")
    assert k1 == k2, "the ' | TICK Stock News' suffix must be normalized out"
    assert article_key("https://x.com/a", "t") != article_key(
        "https://x.com/b", "t",
    )
    sk = split_key("acme", "1-for-40", "March 3, 2026", "round_up")
    assert sk == "ACME|1-FOR-40|MARCH 3, 2026|ROUND_UP"
    # Same economic play, different producers -> identical key.
    assert split_key("ACME", "1-for-40", "March 3, 2026", "ROUND_UP") == sk
    assert split_key("", "1-for-2", "x", "y") == ""
    assert split_key("ACME", "", "", "ROUND_UP") == ""


def test_strip_html():
    assert strip_html("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    assert strip_html("<script>x</script>keep<style>y</style>") == "keep"
