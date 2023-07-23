# Nelson Dane
# Robinhood API

import os
import traceback

import pyotp
import robin_stocks.robinhood as rh
from dotenv import load_dotenv
from helperAPI import Brokerage, printAndDiscord, printHoldings


def robinhood_init(ROBINHOOD_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Robinhood account
    rh_obj = Brokerage("Robinhood")
    if not os.getenv("ROBINHOOD") and ROBINHOOD_EXTERNAL is None:
        print("Robinhood not found, skipping...")
        return None
    RH = os.environ["ROBINHOOD"].strip().split(",") if ROBINHOOD_EXTERNAL is None else ROBINHOOD_EXTERNAL.strip().split(",")
    # Log in to Robinhood account
    for account in RH:
        print("Logging in to Robinhood...")
        index = RH.index(account) + 1
        name = f"Robinhood {index}"
        try:
            account = account.split(":")
            rh.login(
                username=account[0],
                password=account[1],
                mfa_code=None if account[2] == "NA" else pyotp.TOTP(account[2]).now(),
                store_session=False,
            )
            rh_obj.set_logged_in_object(name, rh)
            rh_obj.set_account_number(f"{name}", rh.account.load_account_profile(info="account_number"))
            rh_obj.set_account_totals(f"{name}", rh.account.load_account_profile(info="account_number"), rh.account.load_account_profile(info="portfolio_cash"))
        except Exception as e:
            print(f"Error: Unable to log in to Robinhood: {e}")
            return None
        print("Logged in to Robinhood!")
    return rh_obj


def robinhood_holdings(rho, ctx=None, loop=None):
    for key in rho.get_account_numbers():
        for account in rho.get_account_numbers(key):
            obj = rho.get_logged_in_objects(key)
            try:
                # Get account holdings
                positions = obj.get_open_stock_positions(account_number=account)
                rh_accounts = obj.account.load_account_profile(info="account_number")
                if positions == []:
                    printAndDiscord(f"No holdings in {key}", ctx, loop)
                else:
                    for item in positions:
                        # Get symbol, quantity, price, and total value
                        sym = item["symbol"] = obj.get_symbol_by_url(item["instrument"])
                        qty = float(item["quantity"])
                        try:
                            current_price = round(float(obj.stocks.get_latest_price(sym)[0]), 2)
                        except TypeError as e:
                            if "NoneType" in str(e):
                                current_price = "N/A"
                        rho.set_holdings(key, rh_accounts, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", ctx, loop)
                print(traceback.format_exc())
                continue
        printHoldings(rho, ctx, loop)


def robinhood_transaction(
    rho, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Robinhood")
    print("==============================")
    print()
    action = action.lower()
    stock = [x.upper() for x in stock]
    if amount == "all" and action == "sell":
        all_amount = True
    elif amount < 1:
        amount = float(amount)
    else:
        amount = int(amount)
        all_amount = False
    for s in stock:
        for key in rho.get_account_numbers():
            printAndDiscord(f"{key}: {action}ing {amount} of {s}", ctx, loop)
            for account in rho.get_account_numbers(key):
                obj = rho.get_logged_in_objects(key)
                if not DRY:
                    try:
                        # Buy Market order
                        if action == "buy":
                            result = obj.order_buy_market(symbol=s, quantity=amount, account_number=account)
                            printAndDiscord(f"{key}: Bought {amount} of {s}", ctx, loop)
                        # Sell Market order
                        elif action == "sell":
                            if all_amount:
                                # Get account holdings
                                positions = obj.get_open_stock_positions(account_number=account)
                                for item in positions:
                                    sym = item["symbol"] = obj.get_symbol_by_url(item["instrument"])
                                    if sym.upper() == s:
                                        amount = float(item["quantity"])
                                        break
                            result = obj.order_sell_market(symbol=s, quantity=amount)
                            printAndDiscord(f"{key}: Sold {amount} of {s}: {result}", ctx, loop)
                        else:
                            print("Error: Invalid action")
                            return
                    except Exception as e:
                        printAndDiscord(f"{key} Error submitting order: {e}", ctx, loop)
                else:
                    printAndDiscord(
                        f"{key} Running in DRY mode. Transaction would've been: {action} {amount} of {s}",
                        ctx,
                        loop,
                    )
                