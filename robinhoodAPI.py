# Nelson Dane
# Robinhood API

import asyncio
import os
import traceback

import pyotp
import robin_stocks.robinhood as rh
from dotenv import load_dotenv


def robinhood_init():
    # Initialize .env file
    load_dotenv()
    # Import Robinhood account
    if not os.getenv("ROBINHOOD_USERNAME") or not os.getenv("ROBINHOOD_PASSWORD"):
        print("Robinhood not found, skipping...")
        return None
    RH_USERNAME = os.environ["ROBINHOOD_USERNAME"]
    RH_PASSWORD = os.environ["ROBINHOOD_PASSWORD"]
    if os.environ["ROBINHOOD_TOTP"]:
        RH_TOTP = os.environ["ROBINHOOD_TOTP"]
        totp = pyotp.TOTP(RH_TOTP).now()
    else:
        totp = None
    # Log in to Robinhood account
    print("Logging in to Robinhood...")
    try:
        if not totp:
            rh.login(RH_USERNAME, RH_PASSWORD)
        else:
            print("Using Robinhood TOTP")
            rh.login(RH_USERNAME, RH_PASSWORD, mfa_code=totp)
    except Exception as e:
        print(f"Error: Unable to log in to Robinhood: {e}")
        return None
    print("Logged in to Robinhood!")
    return rh


def robinhood_holdings(rh, ctx=None, loop=None):
    print()
    print("==============================")
    print("Robinhood Holdings")
    print("==============================")
    print()
    # Make sure init didn't return None
    if rh is None:
        print("Error: No Robinhood account")
        return None
    try:
        # Get account holdings
        positions = rh.get_open_stock_positions()
        if positions == []:
            print("No holdings in Robinhood")
            if ctx and loop:
                asyncio.ensure_future(ctx.send("No holdings in Robinhood"), loop=loop)
        else:
            print("Holdings in Robinhood:")
            if ctx and loop:
                asyncio.ensure_future(ctx.send("Holdings in Robinhood:"), loop=loop)
            for item in positions:
                # Get symbol, quantity, price, and total value
                sym = item["symbol"] = rh.get_symbol_by_url(item["instrument"])
                qty = float(item["quantity"])
                try:
                    current_price = round(float(rh.stocks.get_latest_price(sym)[0]), 2)
                    total_value = round(qty * current_price, 2)
                except TypeError as e:
                    if "NoneType" in str(e):
                        current_price = "N/A"
                        total_value = "N/A"
                print(f"{sym}: {qty} @ ${(current_price)} = ${total_value}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"{sym}: {qty} @ ${(current_price)} = ${total_value}"),
                        loop=loop,
                    )
    except Exception as e:
        print(f"Robinhood: Error getting account holdings: {e}")
        print(traceback.format_exc())
        if ctx and loop:
            asyncio.ensure_future(
                ctx.send(f"Robinhood: Error getting account holdings: {e}"), loop=loop
            )


def robinhood_transaction(
    rh, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Robinhood")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    if amount == "all" and action == "sell":
        all_amount = True
    elif amount < 1:
        amount = float(amount)
    else:
        amount = int(amount)
        all_amount = False
    # Make sure init didn't return None
    if rh is None:
        print("Error: No Robinhood account")
        return None
    if not DRY:
        try:
            # Buy Market order
            if action == "buy":
                rh.order_buy_market(stock, amount)
                print(f"Robinhood: Bought {amount} of {stock}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Robinhood: Bought {amount} of {stock}"), loop=loop
                    )
            # Sell Market order
            elif action == "sell":
                if all_amount:
                    # Get account holdings
                    positions = rh.get_open_stock_positions()
                    for item in positions:
                        sym = item["symbol"] = rh.get_symbol_by_url(item["instrument"])
                        if sym.upper() == stock:
                            amount = float(item["quantity"])
                            break
                rh.order_sell_market(stock, amount)
                print(f"Robinhood: Sold {amount} of {stock}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Robinhood: Sold {amount} of {stock}"), loop=loop
                    )
            else:
                print("Error: Invalid action")
                return None
        except Exception as e:
            print(f"Robinhood: Error submitting order: {e}")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(f"Robinhood: Error submitting order: {e}"), loop=loop
                )
    else:
        print(
            f"Robinhood: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}"
        )
        if ctx and loop:
            asyncio.ensure_future(
                ctx.send(
                    f"Robinhood: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}"
                ),
                loop=loop,
            )
