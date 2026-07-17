"""mark_fill: FillState -> ledger status, and PENDING blocks a re-fire.

Regression spine for fill verification. The Chase/Robinhood incident was
a *submitted* order recorded as a *fill*. mark_fill makes the three
states distinct: only FILLED marks EXECUTED; an accepted-but-working
order is PENDING (blocking, not a fill); a rejected/never-placed order is
FAILED (retryable); an ambiguous one is NEEDS_REVIEW.
"""

import pytest

from src import ledger
from src.brokerages.fill_result import FillResult, FillState
from src.ledger import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    Play,
    mark_fill,
    record_intent,
)


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")


def _play(key: str = "SIG:1") -> Play:
    return Play(key, "robinhood", "Z-1", "FOMO", "buy")


def _row(play: Play) -> dict:
    rows = ledger.list_executions(play.key)
    assert rows, "expected a ledger row"
    return rows[0]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (FillState.FILLED, STATUS_EXECUTED),
        (FillState.PENDING, STATUS_PENDING),
        (FillState.REJECTED, STATUS_FAILED),
        (FillState.UNKNOWN, STATUS_NEEDS_REVIEW),
    ],
)
def test_state_maps_to_status(state, expected):
    p = _play()
    assert record_intent(p, 1) is True
    result = FillResult(
        state, broker="robinhood", ticker="FOMO", action="buy",
        order_ref="abc123", qty=1.0, detail="x",
    )
    assert mark_fill(p, result) == expected
    row = _row(p)
    assert row["status"] == expected
    assert row["fill_state"] == state.value
    assert row["order_ref"] == "abc123"


def test_filled_records_qty_reason_and_source():
    p = _play()
    assert record_intent(p, 1) is True
    mark_fill(
        p, FillResult(FillState.FILLED, qty=2.0, order_ref="x"), source="poll",
    )
    row = _row(p)
    assert row["status"] == STATUS_EXECUTED
    assert row["filled_qty"] == 2.0
    assert row["verify_source"] == "poll"
    assert row["reason"] == "OK"


def test_pending_blocks_refire():
    """A working order MIGHT fill, so a re-fire must be blocked — the
    same double-buy conservatism as NEEDS_REVIEW/INTENDED."""
    p = _play()
    assert record_intent(p, 1) is True
    assert mark_fill(p, FillResult(FillState.PENDING, order_ref="o1")) == STATUS_PENDING
    assert ledger.already_done(p) is True
    assert record_intent(p, 1) is False  # blocked, not re-placed


def test_rejected_is_retryable():
    """A rejected/never-placed order left NO live order, so it's safe to
    retry — FAILED resets to INTENDED on the next attempt."""
    p = _play()
    assert record_intent(p, 1) is True
    assert mark_fill(
        p, FillResult(FillState.REJECTED, detail="not available"),
    ) == STATUS_FAILED
    assert record_intent(p, 1) is True


def test_unknown_or_missing_state_defaults_to_needs_review():
    p = _play()
    assert record_intent(p, 1) is True

    class _Bogus:
        state = None
        detail = ""
        order_ref = ""
        qty = None

    # A missing/unrecognized state must resolve to the SAFE non-fill
    # default (a missed buy beats a double-buy), never EXECUTED.
    assert mark_fill(p, _Bogus()) == STATUS_NEEDS_REVIEW
    assert _row(p)["status"] == STATUS_NEEDS_REVIEW
