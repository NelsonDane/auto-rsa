"""Ambiguous-outcome (session-error-after-intent) must NOT be retryable.

Regression for the double-buy: intent is recorded right before the order
is placed, so a session/browser break after that point is ambiguous (the
order may already be live). Marking it retryable FAILED let record_intent
reset it to INTENDED and buy the same share again. It must be blocking
NEEDS_REVIEW instead.
"""

import pytest

from src import ledger
from src.ledger import (
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    Play,
    mark_result,
    record_intent,
)


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")


def _status(play: Play) -> str:
    rows = ledger.list_executions(play.key)
    assert rows, "expected a ledger row"
    return str(rows[0]["status"])


def test_session_error_after_intent_is_needs_review_and_blocks_retry():
    p = Play("SIG:1", "fidelity", "Z-7743", "FOMO", "buy", "FOMO|1-40|X|ROUND_UP")
    assert record_intent(p, 1) is True
    # Order was being placed; the browser died -> ambiguous.
    mark_result(p, success=False, detail="Target closed: browser has been closed")
    assert _status(p) == STATUS_NEEDS_REVIEW
    # A re-fire (same play or same economic split) must be BLOCKED, not
    # reset to INTENDED and re-bought.
    assert record_intent(p, 1) is False
    twin = Play("SIG:2", "fidelity", "Z-7743", "FOMO", "buy", "FOMO|1-40|X|ROUND_UP")
    assert record_intent(twin, 1) is False


def test_benign_failure_stays_retryable_failed():
    p = Play("SIG:9", "fidelity", "Z-7743", "BLAH", "buy")
    assert record_intent(p, 1) is True
    # Stock genuinely unavailable on this broker -> no order placed -> safe
    # to retry later.
    mark_result(p, success=False, detail="Symbol not found: not available here")
    assert _status(p) == STATUS_FAILED
    assert record_intent(p, 1) is True  # FAILED resets to INTENDED (retry ok)
