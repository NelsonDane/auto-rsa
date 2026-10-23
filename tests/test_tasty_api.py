"""Tests for src/brokerages/tasty_api.py order and event-loop handling."""

import asyncio
import threading
from decimal import Decimal
from unittest.mock import patch

from src.brokerages import tasty_api
from src.brokerages.tasty_api import _to_decimal


def test_to_decimal_preserves_fractional_precision() -> None:
    assert _to_decimal(0.05) == Decimal("0.05")
    assert _to_decimal(0.00208) == Decimal("0.00208")
    assert _to_decimal(1.0) == Decimal("1.0")


def test_tastytrade_init_supports_concurrent_calls() -> None:
    async def slow_init() -> None:
        await asyncio.sleep(0.1)

    results: list[str] = []

    def worker() -> None:
        with patch.object(tasty_api, "_tastytrade_async_init", slow_init):
            tasty_api.tastytrade_init()
        results.append("ok")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["ok"] * 4
