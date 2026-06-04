"""BBAE / DSPAC execute-outcome gating (real-money correctness).

Two regressions are locked here:

1. ``execute_buy`` is called WITH the prior ``validation_response``.
   The bbae/dspac libraries refuse to place an order (return
   Outcome=Failed) when it's omitted, so the buy never actually
   happened — yet the ledger used to record EXECUTED regardless.
2. The ledger success flag reflects the execute call's real
   ``Outcome`` — a rejected/failed order stays FAILED (retryable),
   not a false EXECUTED that suppresses the retry and misstates
   holdings.
"""

from __future__ import annotations

import importlib

import pytest

from src.helper_api import Brokerage, StockOrder


class _FakeClient:
    """Minimal stand-in for the bbae/dspac invest-api client."""

    def __init__(self, *, buy_outcome: str) -> None:
        self.buy_outcome = buy_outcome
        self.execute_calls: list[dict] = []

    def validate_buy(self, **_kw):
        return {
            "Outcome": "Success",
            "Message": "validated",
            "Data": {"entrustPrice": 1.0, "type": "MARKET"},
        }

    def execute_buy(self, **kw):
        self.execute_calls.append(kw)
        return {"Outcome": self.buy_outcome, "Message": f"exec {self.buy_outcome}"}


def _brokerage(parent: str, account: str, account_name: str, client: object) -> Brokerage:
    b = Brokerage("bbae")
    b.set_account_number(parent, account)
    b.set_logged_in_object(parent, {}, account_name)
    b.set_logged_in_object(parent, client, account_name)
    return b


def _order() -> StockOrder:
    o = StockOrder()
    o.set_action("buy")
    o.set_amount(1.0)
    o.set_stock("ABCD")
    o.set_dry(dry=False)  # real run so the ledger guard is active
    return o


@pytest.mark.parametrize(
    ("module", "account_name"),
    [("src.brokerages.bbae_api", "bb"), ("src.brokerages.dspac_api", "ds")],
)
@pytest.mark.parametrize(
    ("outcome", "expect_success"),
    [("Success", True), ("Failed", False)],
)
def test_execute_outcome_gates_ledger(
    monkeypatch, module, account_name, outcome, expect_success,
):
    mod = importlib.import_module(module)
    broker_key = module.split(".")[-1].removesuffix("_api")
    transaction = getattr(mod, f"{broker_key}_transaction")

    # Don't touch the real ledger DB: stub the guard primitives that
    # reserve_or_skip / complete_or_fail import lazily from src.ledger.
    import src.ledger as ledger

    monkeypatch.setattr(ledger, "record_intent", lambda *_a, **_k: True)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        ledger,
        "mark_result",
        lambda play, *, success, detail="": captured.update(  # noqa: ARG005
            success=success, detail=detail,
        ),
    )
    monkeypatch.delenv("RSA_ACCOUNT_FILTER", raising=False)

    client = _FakeClient(buy_outcome=outcome)
    bro = _brokerage(broker_key, "12345678", account_name, client)

    transaction(bro, _order(), None)

    # 1) The order was actually attempted with the validation response.
    assert client.execute_calls, "execute_buy was never called"
    assert "validation_response" in client.execute_calls[0]
    # 2) The ledger outcome mirrors the broker's real Outcome.
    assert captured.get("success") is expect_success
