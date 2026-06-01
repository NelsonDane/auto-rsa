"""Per-signal-type aggregator + vault override plumbing (Phase 9)."""

from __future__ import annotations

from src.dashboard.per_signal_type import (
    DEFAULT_AVG_PROFIT_PER_FILL,
    aggregate_by_signal_type,
    overrides_from_settings,
    vault_setting_key,
)


def _row(
    *, key: str, status: str, action: str = "buy",
    signal_type: str = "ROUND_UP_REVERSE",
) -> dict[str, object]:
    return {
        "key": key, "broker": "fidelity", "sub_account": "111",
        "ticker": "ACME", "action": action, "qty": 1.0,
        "status": status, "signal_type": signal_type,
        "hold_until": "", "split_key": "SK",
    }


# --- aggregation ------------------------------------------------------

def test_empty_ledger_returns_zero_rows_for_all_types():
    metrics = aggregate_by_signal_type([])
    # One row per known signal type, all zero.
    assert {m.signal_type for m in metrics} == {
        "ROUND_UP_REVERSE", "SPIN_OFF", "SPECIAL_DIV",
    }
    assert all(m.distinct_alerts == 0 for m in metrics)
    assert all(m.bought == 0 for m in metrics)
    assert all(m.estimated_profit_usd == 0.0 for m in metrics)


def test_bought_count_drives_estimated_profit():
    rows = [
        _row(key="K1", status="EXECUTED"),
        _row(key="K2", status="EXECUTED"),
        _row(key="K3", status="EXECUTED"),
    ]
    metrics = aggregate_by_signal_type(rows)
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.bought == 3
    # 3 buys × default $3.50 = $10.50
    assert round_up.estimated_profit_usd == 3 * DEFAULT_AVG_PROFIT_PER_FILL["ROUND_UP_REVERSE"]


def test_completion_rate_is_sold_over_bought():
    rows = [
        _row(key="K1", status="EXECUTED", action="buy"),
        _row(key="K2", status="EXECUTED", action="buy"),
        _row(key="K3", status="EXECUTED", action="buy"),
        _row(key="K1", status="EXECUTED", action="sell"),
        _row(key="K2", status="EXECUTED", action="sell"),
    ]
    metrics = aggregate_by_signal_type(rows)
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.bought == 3
    assert round_up.sold == 2
    assert round_up.completion_rate == 2 / 3


def test_completion_rate_zero_when_no_buys():
    rows = [_row(key="K1", status="FAILED")]
    metrics = aggregate_by_signal_type(rows)
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.bought == 0
    assert round_up.completion_rate == 0.0


def test_distinct_alerts_dedupes_by_key():
    """Multiple fills for the same play_key (one per broker account)
    are ONE distinct alert from the operator's perspective."""
    rows = [
        _row(key="K1", status="EXECUTED"),
        _row(key="K1", status="EXECUTED"),  # same key, different broker row
        _row(key="K1", status="EXECUTED"),
        _row(key="K2", status="EXECUTED"),
    ]
    metrics = aggregate_by_signal_type(rows)
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.distinct_alerts == 2
    assert round_up.bought == 4  # still 4 actual fills


def test_default_signal_type_when_column_absent():
    """Pre-Phase-5 ledger rows with no signal_type bucket as
    ROUND_UP_REVERSE — same default as the schema migration."""
    rows = [{
        "key": "OLD", "broker": "fidelity", "sub_account": "111",
        "ticker": "ACME", "action": "buy", "qty": 1.0,
        "status": "EXECUTED",
        # No signal_type field at all.
    }]
    metrics = aggregate_by_signal_type(rows)
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.bought == 1


def test_per_type_overrides_replace_defaults():
    rows = [_row(key="K1", status="EXECUTED")]
    metrics = aggregate_by_signal_type(
        rows, avg_profit_overrides={"ROUND_UP_REVERSE": 100.0},
    )
    round_up = next(m for m in metrics if m.signal_type == "ROUND_UP_REVERSE")
    assert round_up.avg_profit_per_fill_usd == 100.0
    assert round_up.estimated_profit_usd == 100.0
    # Other types still use the default.
    spin = next(m for m in metrics if m.signal_type == "SPIN_OFF")
    assert spin.avg_profit_per_fill_usd == DEFAULT_AVG_PROFIT_PER_FILL["SPIN_OFF"]


def test_rows_sorted_by_distinct_alerts_desc():
    rows = [
        _row(key="K1", status="EXECUTED", signal_type="SPIN_OFF"),
        _row(key="K2", status="EXECUTED", signal_type="SPIN_OFF"),
        _row(key="K3", status="EXECUTED", signal_type="SPIN_OFF"),
        _row(key="K4", status="EXECUTED", signal_type="ROUND_UP_REVERSE"),
    ]
    metrics = aggregate_by_signal_type(rows)
    # SPIN_OFF has 3 distinct, ROUND_UP_REVERSE has 1 → SPIN_OFF first.
    assert metrics[0].signal_type == "SPIN_OFF"


# --- vault settings plumbing ------------------------------------------

def test_vault_setting_key_format():
    assert vault_setting_key("SPIN_OFF") == "RSA_AVG_PROFIT_SPIN_OFF"
    assert vault_setting_key("spin_off") == "RSA_AVG_PROFIT_SPIN_OFF"


def test_overrides_from_settings_skips_blank_and_bad():
    settings = {
        "RSA_AVG_PROFIT_ROUND_UP_REVERSE": "7.25",
        "RSA_AVG_PROFIT_SPIN_OFF": "",  # blank — use code default
        "RSA_AVG_PROFIT_SPECIAL_DIV": "bogus",  # unparseable — ignore
    }
    out = overrides_from_settings(settings)
    assert out == {"ROUND_UP_REVERSE": 7.25}
