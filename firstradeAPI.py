# Donald Ryan Gullett(MaxxRK)
# Firstrade API

from firstrade import account as ft_account, symbols, order
import os
import pprint
from time import sleep
from dotenv import load_dotenv

from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


def firstrade_init(FIRSTRADE_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Firstrade account
    if not os.getenv("FIRSTRADE") and FIRSTRADE_EXTERNAL is None:
        print("Firstrade not found, skipping...")
        return None
    accounts = (
        os.environ["FIRSTRADE"].strip().split(",")
        if FIRSTRADE_EXTERNAL is None
        else FIRSTRADE_EXTERNAL.strip().split(",")
    )
    # Log in to Firstrade account
    print("Logging in to Firstrade...")
    firstrade_obj = Brokerage("Firstrade")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Firstrade {index}"
        try:
            account = account.split(":")
            firstrade = ft_account.FTSession(
                username=account[0],
                password=account[1],
                pin=account[2]
            )
            account_info = ft_account.FTAccountData(firstrade)
            account_list = account_info.account_numbers
            print(f"The following Firstrade accounts were found: {account_list}")
            print("Logged in to Firstrade!")
            firstrade_obj.set_logged_in_object(name, firstrade)
            for i, account in enumerate(account_list):
                firstrade_obj.set_account_number(name, account)
                firstrade_obj.set_account_totals(
                    name, account, str(account_info.account_balances[i])
                )
        except Exception as e:
            print(f"Error logging in to Firstrade: {e}")
            return None
    return firstrade_obj


def firstrade_holdings(firstrade_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in firstrade_o.get_account_numbers():
        for account in firstrade_o.get_account_numbers(key):
            obj: Firstrade = firstrade_o.get_logged_in_objects(key)
            try:
                data = ft_account.FTAccountData(obj).get_positions(account=account)
                for item in data:
                    sym = item
                    if sym == "":
                        sym = "Unknown"
                    qty = float(data[item]["quantity"])
                    current_price = float(data[item]["price"])
                    firstrade_o.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
                continue
        printHoldings(firstrade_o, loop)


def firstrade_transaction(firstrade_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Firstrade")
    print("==============================")
    print()
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in firstrade_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            for account in firstrade_o.get_account_numbers(key):
                obj: Firstrade = firstrade_o.get_logged_in_objects(key)
                print(f"{key} Account: {account}")
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    symbol_data = symbols.SymbolQuote(obj, s)
                    if symbol_data.last < 1.00:
                        price_type = order.PriceType.LIMIT
                        if orderObj.get_action().capitalize() == "Buy":
                            price = symbol_data.bid + 0.01
                        else:
                            price = symbol_data.ask - 0.01
                    else:
                        price_type = order.PriceType.MARKET
                        price = 0.00
                    ft_order = order.Order(obj)
                    ft_order.place_order(
                        account=account,
                        symbol=s,
                        order_type=price_type,
                        quantity=int(orderObj.get_amount()),
                        duration=order.Duration.DAY,
                        price=price,
                        dry_run=orderObj.get_dry(),
                    )
                    print("The order verification produced the following messages: ")
                    pprint.pprint(ft_order.order_confirmation)
                    printAndDiscord(
                        f"{key} account {account}: The order verification was "
                        + "successful"
                        if ft_order.order_confirmation["success"] == 'Yes'
                        else "unsuccessful",
                        loop,
                    )
                    if not ft_order.order_confirmation["success"] == 'Yes':
                        printAndDiscord(
                            f"{key} account {account}: The order verification produced the following messages: {ft_order.order_confirmation['actiondata']}",
                            loop,
                        )
                except Exception as e:
                    printAndDiscord(
                        f"{key} {account}: Error submitting order: {e}", loop
                    )
                    continue
                sleep(1)
                print()