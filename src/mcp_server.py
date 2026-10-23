"""MCP server exposing auto-rsa holdings/buy/sell as tools for AI agents."""

import contextlib
import io
import threading
import traceback
from typing import TYPE_CHECKING, Literal

from fastmcp import FastMCP

from src.brokers import AllBrokersInfo, BrokerInfo

if TYPE_CHECKING:
    from src.helper_api import StockOrder

SERVER_INSTRUCTIONS = """\
auto-rsa places/checks brokerage orders across ~16 brokerages (Schwab, Fidelity,
Robinhood, etc). Each brokerage requires its own credentials, supplied as
environment variables to this MCP server process (NOT arguments to the tools).

If a tool's output says a broker was "not found" or "skipped", that broker's
required environment variables are missing. Ask the user to set them either:
  1. In a `.env` file passed to uvx via `--env-file /absolute/path/to/.env`, or
  2. Directly in this MCP server's environment variables config block.

The full list of required environment variables per brokerage is documented at:
https://github.com/NelsonDane/auto-rsa/blob/main/docs/BROKERAGES.md
and an example file with every variable name is at:
https://github.com/NelsonDane/auto-rsa/blob/main/.env.example
To help the user setup the MCP server, instructions are at:
https://github.com/NelsonDane/auto-rsa/blob/main/docs/MCP.md

buy/sell default to dry-run (no real order placed) unless dry=False is passed
explicitly.
"""

mcp = FastMCP("auto-rsa", instructions=SERVER_INSTRUCTIONS)


def _resolve_brokers(all_brokers: AllBrokersInfo, selector: str) -> list[BrokerInfo]:
    """Resolve a broker selector string (e.g. 'all', 'day1', 'schwab,fidelity') to BrokerInfo list."""
    selector = selector.strip().lower()
    if selector in {"", "all"}:
        return all_brokers.get_all()
    if selector == "day1":
        return all_brokers.get_day_one()
    if selector == "most":
        return all_brokers.get_most()
    if selector == "fast":
        return all_brokers.get_fast()
    resolved = []
    for name in selector.split(","):
        broker = all_brokers.parse_input(name.strip())
        if broker:
            resolved.append(broker)
    return resolved


# redirect_stdout swaps the process-wide sys.stdout, so concurrent tool calls must not overlap
_CAPTURE_LOCK = threading.Lock()


def _run_captured(order_obj: "StockOrder") -> str:
    """Run fun_run() while capturing its stdout output, returning it as a string."""
    buffer = io.StringIO()
    with _CAPTURE_LOCK:
        try:
            with contextlib.redirect_stdout(buffer):
                # Imported lazily inside the redirect so auto_rsa's heavy broker
                # imports / startup prints don't run or leak into the MCP stdio stream.
                from src.auto_rsa import fun_run  # ruff: ignore[import-outside-top-level]

                fun_run(order_obj)
        except Exception:
            buffer.write("\n")
            buffer.write(traceback.format_exc())
    return buffer.getvalue()


@mcp.tool
def get_holdings(brokers: str = "all", not_brokers: str = "") -> str:
    """Get current holdings/account totals from one or more brokerages.

    Args:
        brokers: Which brokerages to check. One of "all", "day1", "most",
            "fast", or a comma-separated list of broker names/nicknames
            (e.g. "schwab,fidelity").
        not_brokers: Comma-separated brokerages to exclude from the selection.

    """
    from src.helper_api import StockOrder  # ruff: ignore[import-outside-top-level]

    all_brokers = AllBrokersInfo()
    order_obj = StockOrder()
    order_obj.set_holdings(holdings=True)
    order_obj.set_brokers(_resolve_brokers(all_brokers, brokers))
    if not_brokers:
        order_obj.set_notbrokers(_resolve_brokers(all_brokers, not_brokers))
    order_obj.order_validate(pre_login=True)
    return _run_captured(order_obj)


def _place_order(  # ruff: ignore[too-many-arguments]
    action: Literal["buy", "sell"],
    amount: float,
    stock: str,
    brokers: str,
    not_brokers: str,
    *,
    dry: bool,
) -> str:
    from src.helper_api import StockOrder  # ruff: ignore[import-outside-top-level]

    all_brokers = AllBrokersInfo()
    order_obj = StockOrder()
    order_obj.set_action(action)
    order_obj.set_amount(amount)
    for ticker in stock.split(","):
        ticker = ticker.strip()  # ruff: ignore[redefined-loop-name]
        if ticker:
            order_obj.set_stock(ticker)
    order_obj.set_brokers(_resolve_brokers(all_brokers, brokers))
    if not_brokers:
        order_obj.set_notbrokers(_resolve_brokers(all_brokers, not_brokers))
    order_obj.set_dry(dry=dry)
    order_obj.order_validate(pre_login=True)
    return _run_captured(order_obj)


@mcp.tool
def buy(
    amount: float,
    stock: str,
    brokers: str = "all",
    not_brokers: str = "",
    *,
    dry: bool = True,
) -> str:
    """Buy stock across one or more brokerages.

    Args:
        amount: Number of shares (or dollar amount, depending on broker) to buy.
        stock: Comma-separated stock ticker(s) to buy, e.g. "AAPL" or "AAPL,MSFT".
        brokers: Which brokerages to use. One of "all", "day1", "most", "fast",
            or a comma-separated list of broker names/nicknames.
        not_brokers: Comma-separated brokerages to exclude from the selection.
        dry: If True (default), simulate the order without placing a real trade.
            Must be explicitly set to False to place a real order.

    """
    return _place_order("buy", amount, stock, brokers, not_brokers, dry=dry)


@mcp.tool
def sell(
    amount: float,
    stock: str,
    brokers: str = "all",
    not_brokers: str = "",
    *,
    dry: bool = True,
) -> str:
    """Sell stock across one or more brokerages.

    Args:
        amount: Number of shares (or dollar amount, depending on broker) to sell.
        stock: Comma-separated stock ticker(s) to sell, e.g. "AAPL" or "AAPL,MSFT".
        brokers: Which brokerages to use. One of "all", "day1", "most", "fast",
            or a comma-separated list of broker names/nicknames.
        not_brokers: Comma-separated brokerages to exclude from the selection.
        dry: If True (default), simulate the order without placing a real trade.
            Must be explicitly set to False to place a real order.

    """
    return _place_order("sell", amount, stock, brokers, not_brokers, dry=dry)


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    run()
