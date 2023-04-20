from datetime import date
import os
from decimal import Decimal as D

from tastyworks.models.order_type import Equity
from tastyworks.models.order import (Order, OrderDetails, OrderPriceEffect,
                                     OrderType, TimeInForce)
from tastyworks.models.session import TastyAPISession
from tastyworks.models.trading_account import TradingAccount
from tastyworks.models.underlying import UnderlyingType
from tastyworks.streamer import DataStreamer
from tastyworks.tastyworks_api import tasty_session
from tastyworks.models.security import Security
from time import sleep
from dotenv import load_dotenv


def tastytrade_init():
    try:
        load_dotenv()
        # Import Tastytrade account
        if not os.getenv("TASTY_USERNAME") or not os.getenv("TASTY_PASSWORD"):
            print("Robinhood not found, skipping...")
            return None
        TASTY_USERNAME = os.environ["TASTY_USERNAME"]
        TASTY_PASSWORD = os.environ["TASTY_PASSWORD"]

        # Log in to Tastytrade account
        print("Logging in to Tastytrade...")
        tastytrade_session = tasty_session.create_new_session(TASTY_USERNAME, TASTY_PASSWORD)
        print("Logged in to Tastytrade!")
        return tastytrade_session
    except Exception as e:
        print(f'Error logging in to Tradier: {e}')
        return None



async def tastytrade_holdings(tastytrade_session, ctx):
    print()
    print("==============================")
    print("Tastytrade Holdings")
    print("==============================")
    print()
    if tastytrade_session is None:
        print("Error: No Tastytrade account")
        return None
    accounts = await TradingAccount.get_remote_accounts(tastytrade_session)
    all_account_balance = 0
    
    for account in accounts:
        balances = await account.get_balance(tastytrade_session)
        cash_balance = (balances['cash-balance'])
        all_account_balance += D(cash_balance)
        positions = await account.get_positions(tastytrade_session)
        stocks = []
        amounts = []
        current_price = []
        if len(positions) == 1:
           stocks.append(positions[0]['symbol'])
           amounts.append(positions[0]['quantity'])
           current_price.append(positions[0]['average-daily-market-close-price'])
        else:
            for stock in positions:
                stocks.append(stock['symbol'])
                amounts.append(stock['quantity'])
                current_price.append(stock['average-daily-market-close-price'])
        current_value = []
        for value in stocks:
            i = stocks.index(value)
            temp_value = round((float(amounts[i]) * float(current_price[i])), 2)
            current_value.append(temp_value)
        print(f"Holdings on Tastytrade account {account.account_number}")
        if ctx:
                await ctx.send(f"Holdings on Tastytrade account {account.account_number}")
        for position in stocks:
            i = stocks.index(position)
            print(f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}")
            if ctx:
                await ctx.send(f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}")
        print(f'Account cash balance is {cash_balance}.')
        if ctx:
            await ctx.send(f"Account cash balance is {cash_balance}.")
    print(f'All accounts cash balance is {all_account_balance}.')
    if ctx:
        await ctx.send(f"All accounts cash balance is {all_account_balance}.")
    

async def tastytrade_transaction(tastytrade_session, action, stock, amount, price, time, DRY=True, ctx=None):
    print()
    print("==============================")
    print("Tastytrade")
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
    if tastytrade_session is None:
        print("Error: No Tastytrade account")
        return None
    accounts = await TradingAccount.get_remote_accounts(tastytrade_session)
    stock_price = Security(stock)
    await stock_price.get_security_price(tastytrade_session)
    stock_price = D(stock_price.bid)
    print(f'Tastyworks Ticker {stock} bid is: ${round(stock_price, 2)}')
    if action == 'buy':
        # Execute an order
        stock_price += D(0.01)
        action = 'Buy to Open'
        details = OrderDetails(
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            price=stock_price,
            price_effect=OrderPriceEffect.DEBIT)
        new_order = Order(details)
    elif action == 'sell':
        if all_amount:
            for index, acct in enumerate(accounts):
                res = await accounts[index].get_balance(tastytrade_session)
                print(res)
                print('Tastytrade: does not support selling "all" of a position yet.')
        # Execute an order
        stock_price -= D(0.01)
        action = 'Sell to Close'
        details = OrderDetails(
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            price=stock_price,
            price_effect=OrderPriceEffect.CREDIT)
        new_order = Order(details)  
    leg = Equity(
            action=action,
            ticker=stock,
            quantity=amount)
    new_order.add_leg(leg)
    for index, acct in enumerate(accounts):
        if not DRY:
            json_response = await accounts[index].execute_order(new_order, tastytrade_session, dry_run=DRY)
            if json_response['order']['status'] == 'Routed':
                print(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                if ctx:
                    await ctx.send(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                sleep(2)
            else:
                print(f"Tastytrade account {acct.account_number} Error: {json_response['id']['status']}")
                if ctx:
                    await ctx.send(f"Tastytrade account {acct.account_number} Error: {json_response['id']['status']}")
                return None
        else:
            print(f"Tastytrade: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}")
            if ctx:
                await ctx.send(f"Tastytrade: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}")
