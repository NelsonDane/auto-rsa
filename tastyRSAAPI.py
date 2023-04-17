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
        print(f'Account {account.account_number} has a cash balance of {cash_balance}.')
        if ctx:
            await ctx.send(f"Account {account.account_number} has a cash balance of {cash_balance}.")
    print(f'All accounts cash balance is {all_account_balance}.')
    if ctx:
        await ctx.send(f"All accounts cash balance is {all_account_balance}.")
    

async def tastytrade_transaction(tastytrade_session, action, stock, amount, time, DRY=True, ctx=None):

    accounts = await TradingAccount.get_remote_accounts(tastytrade_session)
    stock_price= Security(stock)
    await stock_price.get_security_price(ticker=stock_price, session=tastytrade_session)
    print(f'Stock price: {stock_price.price}')
    stock_price = D(stock_price.price)

    if action == 'buy':
        # Execute an order
        stock_price += 0.01
        action = 'Buy to Open'
        details = OrderDetails(
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            price=stock_price,
            price_effect=OrderPriceEffect.DEBIT)
        new_order = Order(details)

    if action == 'sell':
        # Execute an order
        stock_price -= 0.01
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
    

    for acct in range(0, len(accounts)):
        res = await accounts[acct].execute_order(new_order, tastytrade_session, dry_run=DRY)
        print(f'Order executed successfully: {res}')
        sleep(2)