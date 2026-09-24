"""Tests for src/mcp_server.py MCP tool wrappers."""

import sys
import threading
import time
from unittest.mock import patch

import pytest

from src.brokers import BrokerName
from src.helper_api import StockOrder
from src.mcp_server import _resolve_brokers, buy, get_holdings, sell
from src.brokers import AllBrokersInfo


def test_resolve_brokers_all() -> None:
    all_brokers = AllBrokersInfo()
    assert _resolve_brokers(all_brokers, "all") == all_brokers.get_all()


def test_resolve_brokers_named_list() -> None:
    all_brokers = AllBrokersInfo()
    resolved = _resolve_brokers(all_brokers, "schwab,fidelity")
    assert [b.name for b in resolved] == [BrokerName.SCHWAB, BrokerName.FIDELITY]


def test_resolve_brokers_unknown_is_skipped() -> None:
    all_brokers = AllBrokersInfo()
    resolved = _resolve_brokers(all_brokers, "not_a_broker")
    assert resolved == []


def test_get_holdings_builds_order_and_calls_fun_run() -> None:
    with patch("src.auto_rsa.fun_run") as mock_fun_run:
        result = get_holdings(brokers="schwab")
    mock_fun_run.assert_called_once()
    order_obj = mock_fun_run.call_args[0][0]
    assert order_obj.get_holdings() is True
    assert [b.name for b in order_obj.get_brokers()] == [BrokerName.SCHWAB]
    assert isinstance(result, str)


def test_get_holdings_excludes_not_brokers() -> None:
    with patch("src.auto_rsa.fun_run") as mock_fun_run:
        get_holdings(brokers="all", not_brokers="schwab")
    order_obj = mock_fun_run.call_args[0][0]
    assert [b.name for b in order_obj.get_notbrokers()] == [BrokerName.SCHWAB]


def test_buy_defaults_to_dry_run() -> None:
    with patch("src.auto_rsa.fun_run") as mock_fun_run:
        buy(amount=1.0, stock="AAPL", brokers="schwab")
    order_obj = mock_fun_run.call_args[0][0]
    assert order_obj.get_dry() is True
    assert order_obj.get_action() == "buy"
    assert order_obj.get_amount() == 1.0
    assert order_obj.get_stocks() == ["AAPL"]


def test_buy_can_disable_dry_run_explicitly() -> None:
    with patch("src.auto_rsa.fun_run") as mock_fun_run:
        buy(amount=1.0, stock="AAPL", brokers="schwab", dry=False)
    order_obj = mock_fun_run.call_args[0][0]
    assert order_obj.get_dry() is False


def test_sell_builds_order_correctly() -> None:
    with patch("src.auto_rsa.fun_run") as mock_fun_run:
        sell(amount=2.0, stock="AAPL,MSFT", brokers="schwab")
    order_obj = mock_fun_run.call_args[0][0]
    assert order_obj.get_action() == "sell"
    assert order_obj.get_stocks() == ["AAPL", "MSFT"]


def test_buy_missing_broker_raises_validation_error() -> None:
    with pytest.raises(ValueError, match="Broker"):
        buy(amount=1.0, stock="AAPL", brokers="not_a_real_broker")


def test_concurrent_calls_do_not_mix_captured_output() -> None:
    real_stdout = sys.stdout

    def fake_fun_run(order_obj: StockOrder) -> None:
        tag = order_obj.get_stocks()[0]
        print(f"start-{tag}")
        time.sleep(0.2)
        print(f"end-{tag}")

    results: dict[str, str] = {}

    def call(ticker: str) -> None:
        results[ticker] = buy(amount=1.0, stock=ticker, brokers="schwab")

    with patch("src.auto_rsa.fun_run", side_effect=fake_fun_run):
        threads = [threading.Thread(target=call, args=(t,)) for t in ("AAA", "BBB")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert results["AAA"].split() == ["start-AAA", "end-AAA"]
    assert results["BBB"].split() == ["start-BBB", "end-BBB"]
    assert sys.stdout is real_stdout


def test_get_holdings_captures_fun_run_exception_as_text() -> None:
    with patch("src.auto_rsa.fun_run", side_effect=RuntimeError("boom")):
        result = get_holdings(brokers="schwab")
    assert "boom" in result
