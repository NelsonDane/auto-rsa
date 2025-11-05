# Donald Ryan Gullett
# TastyTrade API

import asyncio
import os
import traceback
from decimal import Decimal
from typing import cast

from dotenv import load_dotenv
from tastytrade import Session
from tastytrade.account import Account
from tastytrade.dxfeed import Profile, Quote
from tastytrade.instruments import Equity
from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType
from tastytrade.streamer import DXLinkStreamer
from tastytrade.utils import TastytradeError

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord


def _order_setup(tt: Session, order_type: list[str], stock_price: Decimal, stock: str, amount: float) -> NewOrder:
    symbol = Equity.get_equity(tt, stock)
    if order_type[2] == "Buy to Open":
        leg = symbol.build_leg(Decimal(amount), OrderAction.BUY_TO_OPEN)
    elif order_type[2] == "Sell to Close":
        leg = symbol.build_leg(Decimal(amount), OrderAction.SELL_TO_CLOSE)
    else:
        msg = f"Invalid order type: {order_type[2]}"
        raise ValueError(msg)
    return NewOrder(
        time_in_force=OrderTimeInForce.DAY,
        order_type=OrderType.MARKET,
        legs=[leg],
        price=stock_price if order_type[0] == "Limit" else None,
    )


def tastytrade_init() -> Brokerage | None:
    """Initialize the Tastytrade API."""
    # Initialize .env file
    load_dotenv()
    # Import Tastytrade account
    if not os.getenv("TASTYTRADE"):
        print("Tastytrade not found, skipping...")
        return None
    accounts = os.environ["TASTYTRADE"].strip().split(",")
    tasty_obj = Brokerage("Tastytrade")
    # Log in to Tastytrade account
    print("Logging in to Tastytrade...")
    for account in accounts:
        index = accounts.index(account) + 1
        account_creds = account.strip().split(":")
        name = f"Tastytrade {index}"
        try:
            tasty = Session(account_creds[0], account_creds[1])
            tasty_obj.set_logged_in_object(name, tasty, "session")
            an = Account.get_accounts(tasty)
            tasty_obj.set_logged_in_object(name, an, "accounts")
            for acct in an:
                tasty_obj.set_account_number(name, acct.account_number)
                tasty_obj.set_account_totals(name, acct.account_number, float(acct.get_balances(tasty).cash_balance))
            print("Logged in to Tastytrade!")
        except Exception as e:
            traceback.print_exc()
            print(f"Error logging in to {name}: {e}")
            return None
    return tasty_obj


def tastytrade_holdings(tt_o: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Tastytrade account holdings."""
    for key in tt_o.get_account_numbers():
        obj = cast("Session", tt_o.get_logged_in_objects(key, "session"))
        for index, account in enumerate(cast("list[Account]", tt_o.get_logged_in_objects(key, "accounts"))):
            try:
                an = tt_o.get_account_numbers(key)[index]
                positions = account.get_positions(obj)
                for pos in positions:
                    tt_o.set_holdings(
                        key,
                        an,
                        pos.symbol,
                        float(pos.quantity),
                        "N/A" if pos.average_daily_market_close_price is None else float(pos.average_daily_market_close_price),
                    )
            except Exception as e:
                print_and_discord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(tt_o, loop=loop)


async def _tastytrade_execute(tt_o: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
    print()
    print("==============================")
    print("Tastytrade")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in tt_o.get_account_numbers():
            obj = cast("Session", tt_o.get_logged_in_objects(key, "session"))
            accounts = cast("list[Account]", tt_o.get_logged_in_objects(key, "accounts"))
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop=loop,
            )
            for i in range(len(tt_o.get_account_numbers(key))):
                acct: Account = accounts[i]
                print_account = mask_string(acct.account_number)
                try:
                    # Set order type
                    order_type = ["Market", "Debit", "Buy to Open"] if order_obj.get_action() == "buy" else ["Market", "Credit", "Sell to Close"]
                    # Set stock price
                    stock_price = Decimal(0)
                    # Skip day trade check for now
                    # Place order
                    new_order = _order_setup(
                        obj,
                        order_type,
                        stock_price,
                        s,
                        order_obj.get_amount(),
                    )
                    try:
                        placed_order = acct.place_order(
                            obj,
                            new_order,
                            dry_run=order_obj.get_dry(),
                        )
                        order_status = placed_order.order.status.value
                    except Exception as e:
                        print_and_discord(
                            f"{key} {print_account}: Error placing order: {e}",
                            loop=loop,
                        )
                        continue
                    # Check order status
                    if order_status in {"Received", "Routed"}:
                        message = f"{key} {print_account}: {order_obj.get_action()} {order_obj.get_amount()} of {s} Order: {placed_order.order.id} Status: {order_status}"
                        if order_obj.get_dry():
                            message = f"{key} Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}"
                        print_and_discord(message, loop=loop)
                    elif order_status == "Rejected":
                        # Retry with limit order
                        streamer = await DXLinkStreamer(obj)
                        stock_limit = await streamer.subscribe(Profile, [s])
                        stock_quote = await streamer.subscribe(Quote, [s])
                        stock_limit = await streamer.get_event(Profile)
                        stock_quote = await streamer.get_event(Quote)
                        print_and_discord(
                            f"{key} {print_account} Error: {order_status} Trying Limit order...",
                            loop=loop,
                        )
                        # Get limit price
                        if order_obj.get_action() == "buy":
                            stock_limit = stock_limit.high_limit_price
                            stock_price = Decimal(stock_quote.ask_price) if stock_limit is None else stock_limit
                            order_type = ["Market", "Debit", "Buy to Open"]
                        elif order_obj.get_action() == "sell":
                            stock_limit = stock_limit.low_limit_price
                            stock_price = Decimal(stock_quote.bid_price) if stock_limit is None else stock_limit
                            order_type = ["Market", "Credit", "Sell to Close"]
                        print(f"{s} limit price is: ${round(stock_price, 2)}")
                        # Retry order
                        new_order = _order_setup(
                            obj,
                            order_type,
                            stock_price,
                            s,
                            order_obj.get_amount(),
                        )
                        placed_order = acct.place_order(
                            obj,
                            new_order,
                            dry_run=order_obj.get_dry(),
                        )
                        # Check order status
                        if order_status in {"Received", "Routed"}:
                            message = f"{key} {print_account}: {order_obj.get_action()} {order_obj.get_amount()} of {s} Order: {placed_order.order.id} Status: {order_status}"
                            if order_obj.get_dry():
                                message = f"{key} Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}"
                            print_and_discord(message, loop=loop)
                        elif order_status == "Rejected":
                            # Only want this message if it fails both orders.
                            print_and_discord(
                                f"{key} Error placing order: {placed_order.order.id} on account {print_account}: {order_status}",
                                loop=loop,
                            )
                except (TastytradeError, KeyError) as te:
                    print_and_discord(f"{key} {print_account}: Error: {te}", loop=loop)
                    continue


def tastytrade_transaction(tt: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Execute a Tastytrade transaction."""
    asyncio.run(_tastytrade_execute(tt_o=tt, order_obj=order_obj, loop=loop))
