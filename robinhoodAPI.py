# Nelson Dane
# Robinhood API

import os
import traceback

import pyotp
import robin_stocks.robinhood as rh
from dotenv import load_dotenv

from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


def robinhood_init(ROBINHOOD_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Robinhood account
    rh_obj = Brokerage("Robinhood")
    if not os.getenv("ROBINHOOD") and ROBINHOOD_EXTERNAL is None:
        print("Robinhood not found, skipping...")
        return None
    RH = (
        os.environ["ROBINHOOD"].strip().split(",")
        if ROBINHOOD_EXTERNAL is None
        else ROBINHOOD_EXTERNAL.strip().split(",")
    )
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
                mfa_code=None
                if account[2].upper() == "NA"
                else pyotp.TOTP(account[2]).now(),
                store_session=False,
            )
            rh_obj.set_logged_in_object(name, rh)
            # Check for IRA accounts
            if (len(account) > 3) and (account[3].upper() != "NA"):
                for ira in account[3].split(","):
                    ira_num = rh.account.load_account_profile(
                        info="account_number", account_number=ira
                    )
                    rh_obj.set_account_number(name, ira_num)
                    rh_obj.set_account_totals(
                        name,
                        ira_num,
                        rh.account.load_account_profile(
                            info="portfolio_cash", account_number=ira_num
                        ),
                    )
                    rh_obj.set_account_type(
                        name,
                        ira_num,
                        rh.account.load_account_profile(
                            info="type", account_number=ira_num
                        ),
                    )
            # Normal account
            an = rh.account.load_account_profile(info="account_number")
            rh_obj.set_account_number(name, an)
            rh_obj.set_account_totals(
                name,
                an,
                rh.account.load_account_profile(
                    info="portfolio_cash", account_number=an
                ),
            )
            rh_obj.set_account_type(
                name,
                an,
                rh.account.load_account_profile(info="type", account_number=an),
            )
        except Exception as e:
            print(f"Error: Unable to log in to Robinhood: {e}")
            return None
        print("Logged in to Robinhood!")
    return rh_obj


def robinhood_holdings(rho: Brokerage, loop=None):
    for key in rho.get_account_numbers():
        for account in rho.get_account_numbers(key):
            obj: rh = rho.get_logged_in_objects(key)
            try:
                # Get account holdings
                positions = obj.get_open_stock_positions(account_number=account)
                if positions != []:
                    for item in positions:
                        # Get symbol, quantity, price, and total value
                        sym = item["symbol"] = obj.get_symbol_by_url(item["instrument"])
                        qty = float(item["quantity"])
                        try:
                            current_price = round(
                                float(obj.stocks.get_latest_price(sym)[0]), 2
                            )
                        except TypeError as e:
                            if "NoneType" in str(e):
                                current_price = "N/A"
                        rho.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
        printHoldings(rho, loop)


def robinhood_transaction(rho: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Robinhood")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in rho.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in rho.get_account_numbers(key):
                obj: rh = rho.get_logged_in_objects(key)
                if not orderObj.get_dry():
                    try:
                        # Market order
                        market_order = obj.order(
                            symbol=s,
                            quantity=orderObj.get_amount(),
                            side=orderObj.get_action(),
                            account_number=account,
                        )
                        # Limit order fallback
                        if market_order is None:
                            printAndDiscord(
                                f"{key}: Error {orderObj.get_action()}ing {orderObj.get_amount()} of {s} in {account}, trying Limit Order",
                                loop,
                            )
                            ask = obj.get_latest_price(s, priceType="ask_price")[0]
                            bid = obj.get_latest_price(s, priceType="bid_price")[0]
                            if ask is not None and bid is not None:
                                print(f"Ask: {ask}, Bid: {bid}")
                                # Add or subtract 1 cent to ask or bid
                                if orderObj.get_action() == "buy":
                                    price = (
                                        float(ask)
                                        if float(ask) > float(bid)
                                        else float(bid)
                                    )
                                    price = round(price + 0.01, 2)
                                else:
                                    price = (
                                        float(ask)
                                        if float(ask) < float(bid)
                                        else float(bid)
                                    )
                                    price = round(price - 0.01, 2)
                            else:
                                printAndDiscord(
                                    f"{key}: Error getting price for {s}", loop
                                )
                                continue
                            limit_order = obj.order(
                                symbol=s,
                                quantity=orderObj.get_amount(),
                                side=orderObj.get_action(),
                                limitPrice=price,
                                account_number=account,
                            )
                            if limit_order is None:
                                printAndDiscord(
                                    f"{key}: Error {orderObj.get_action()}ing {orderObj.get_amount()} of {s} in {account}",
                                    loop,
                                )
                                continue
                            printAndDiscord(
                                f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {account} @ {price}: Success",
                                loop,
                            )
                        else:
                            printAndDiscord(
                                f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {account}: Success",
                                loop,
                            )
                    except Exception as e:
                        print(traceback.format_exc())
                        printAndDiscord(f"{key} Error submitting order: {e}", loop)
                else:
                    printAndDiscord(
                        f"{key} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                        loop,
                    )
