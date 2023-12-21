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
            atype = rh.account.load_account_profile(info="type", account_number=an)
            rh_obj.set_account_type(name, an, atype)
            print(f"Found {atype} account {rh_obj.print_account_number(an)}")
            # Check for IRA accounts
            if (len(account) > 3) and (account[3] != "NA"):
                iras = [account[3]]
                if len(account) > 4 and account[4] != "NA":
                    iras.append(account[4])
                for ira in iras:
                    # Make sure it's different from the normal account number
                    if ira == an:
                        ira = rh_obj.print_account_number(ira)
                        print(
                            f"ERROR: IRA account {ira} is the same as margin account. Please remove {an} from your .env file."
                        )
                        continue
                    ira_num = rh.account.load_account_profile(
                        info="account_number", account_number=ira
                    )
                    if ira_num is None:
                        print(f"Unable to lookup IRA account {rh_obj.print_account_number(ira)}")
                        continue
                    print(f"Found IRA account {rh_obj.print_account_number(ira_num)}")
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
        except Exception as e:
            print(f"Error: Unable to log in to Robinhood: {e}")
            traceback.format_exc()
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
                traceback.format_exc()
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
                print_account = rho.print_account_number(account)
                if not orderObj.get_dry():
                    try:
                        # Market order
                        market_order = obj.order(
                            symbol=s,
                            quantity=orderObj.get_amount(),
                            side=orderObj.get_action(),
                            account_number=account,
                            timeInForce="gfd",
                        )
                        # Limit order fallback
                        if market_order is None:
                            printAndDiscord(
                                f"{key}: Error {orderObj.get_action()}ing {orderObj.get_amount()} of {s} in {print_account}, trying Limit Order",
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
                                timeInForce="gfd",
                            )
                            if limit_order is None:
                                printAndDiscord(
                                    f"{key}: Error {orderObj.get_action()}ing {orderObj.get_amount()} of {s} in {print_account}",
                                    loop,
                                )
                                continue
                            message = "Success"
                            if limit_order.get("non_field_errors") is not None:
                                message = limit_order["non_field_errors"]
                            printAndDiscord(
                                f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account} @ {price}: {message}",
                                loop,
                            )
                        else:
                            message = "Success"
                            if market_order.get("non_field_errors") is not None:
                                message = market_order["non_field_errors"]
                            printAndDiscord(
                                f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: {message}",
                                loop,
                            )
                    except Exception as e:
                        traceback.format_exc()
                        printAndDiscord(f"{key} Error submitting order: {e}", loop)
                else:
                    printAndDiscord(
                        f"{key} {print_account} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                        loop,
                    )
