# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import sys
from time import sleep
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
# Custom API libraries
from allyAPI import *
#from fidelityAPI import *
from robinhoodAPI import *
from schwabAPI import *
from webullAPI import *
from tradierAPI import *

brokerages = ["all", "ally", "fidelity", "robinhood", "rh", "schwab", "webull", "wb", "tradier"]

# Get stock info from command line arguments
if len(sys.argv) > 1:
    wanted_action = sys.argv[1]
    if sys.argv[2] is type (int):
        wanted_amount = sys.argv[2]
    elif sys.argv[2] is type (str) and sys.argv[2] == "all":
        wanted_amount = "all"
    else:
        print("Error: Invalid amount")
        sys.exit(1)
    wanted_stock = sys.argv[3].upper()
    wanted_time = "day" # Only supports day for now
    wanted_price = "market" # Only supports market for now
    # Check if DRY mode is enabled   
    if (sys.argv[4].lower()) == "dry" and not (sys.argv[4].lower() in brokerages):
        DRY = True
        single_broker = "all"
    elif sys.argv[4].lower() in brokerages:
        single_broker = sys.argv[4].lower()
    if len(sys.argv) > 5:
        if sys.argv[5].lower() == "dry":
            DRY = True
        else:
            DRY = False
    print(f"Action: {wanted_action}")
    print(f"Amount: {wanted_amount}")
    print(f"Stock: {wanted_stock}")
    print(f"Time: {wanted_time}")
    print(f"Price: {wanted_price}")
    print(f"Broker: {single_broker}")
    print(f"DRY: {DRY}")
    cli_mode = True
else:
    cli_mode = False

# Initialize .env file
load_dotenv()

# Get discord token and prefix from .env file, setting to None if not found
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN and not cli_mode:
    DISCORD = True
else:
    DISCORD = False
    ctx = None

# Raise error if no command line arguments and no discord token
if not cli_mode and not DISCORD:
    print("Error: No command line arguments and no discord token")
    sys.exit(1)
elif not cli_mode and DISCORD:
    single_broker = "all"
    wanted_time = "day"
    wanted_price = "market"

if DISCORD:
    # Discord bot command prefix
    bot = commands.Bot(command_prefix='!')
    print()
    print('Discord bot is started...')
    print()

# Bot ping-pong
if DISCORD:
    @bot.command(name='ping')
    async def ping(ctx):
        print('ponged')
        await ctx.send('pong')

# Initialize Accounts
if single_broker == "all":
    print("==========================================================")
    print("Initializing Accounts...")
    print("==========================================================")
    print()
    ally_account = ally_init()
    print()
    #fidelity_init(fidelity_user, fidelity_password)
    #print()
    robinhood = robinhood_init()
    print()
    schwab = schwab_init()
    print()
    webull_account = webull_init()
    print()
    tradier = tradier_init()
    print()
elif single_broker == "ally":
    ally_account = ally_init()
    print()
elif single_broker == "fidelity":
    #fidelity_init(fidelity_user, fidelity_password)
    print("bruh")
elif single_broker == "robinhood" or single_broker == "rh":
    robinhood = robinhood_init()
    print()
elif single_broker == "schwab":
    schwab = schwab_init()
    print()
elif single_broker == "webull" or single_broker == "wb":
    webull_account = webull_init()
    print()
elif single_broker == "tradier":
    tradier = tradier_init()
    print()
else:
    print("Error: Invalid broker")
    sys.exit(1)

if DISCORD:
    print("Waiting for Discord commands...")
    print()

async def place_order(wanted_action, wanted_amount, wanted_stock, single_broker, DRY=True, ctx=None):
    try:
        # Input validation
        wanted_amount = int(wanted_amount)
        wanted_stock = wanted_stock.upper()
        single_broker = single_broker.lower()
        # Shut up, grammar is important smh
        if wanted_amount > 1:
            grammar = "shares"
        else:
            grammar = "share"
        print("==========================================================")
        print(f"Order: {wanted_action} {wanted_amount} {grammar} of {wanted_stock} on {single_broker}")
        print("==========================================================")
        print()
        # Buy/Sell stock on each account if "all"
        if single_broker == "all":
            # Ally
            await ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # Robinhood
            await robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # Schwab
            await schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # Webull
            await webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # Tradier
            await tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        elif single_broker == "ally":
            # Ally
            await ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        elif single_broker == "fidelity":
            # Fidelity
            #fidelity_transaction(fidelity_user, fidelity_password, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
            print("bruh")
        elif single_broker == "robinhood" or single_broker == "rh":
            # Robinhood
            await robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        elif single_broker == "schwab":
            # Schwab
            #print("bruh")
            await schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        elif single_broker == "webull" or single_broker == "wb":
            # Webull
            await webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        elif single_broker == "tradier":
            # Tradier
            await tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
        else:
            # Invalid broker
            print("Error: Invalid broker")
            await ctx.send("Error: Invalid broker")
    except Exception as e:
        print(f"Error placing order: {e}")  
        await ctx.send(f"Error placing order: {e}")

# If run from the command line, run once and exit
if cli_mode and not DISCORD:
    # Run place order function then exit
    try:
        asyncio.run(place_order(wanted_action, wanted_amount, wanted_stock, single_broker, DRY))
        sys.exit(0)
    # If error, exit with error code
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
# If run from Discord, run forever
elif not cli_mode and DISCORD:
    @bot.command(name='rsa')
    async def rsa(ctx, wanted_action, wanted_amount, wanted_stock, wanted_account, DRY):
        if DRY.lower() == "dry" or DRY.lower() == "true":
            DRY = True
        else:
            DRY = False
        try:
            await place_order(wanted_action, wanted_amount, wanted_stock, wanted_account, DRY, ctx)
        except discord.ext.commands.errors.MissingRequiredArgument:
            # Missing required argument
            print("Error: Missing required argument")
            await ctx.send("Error: Missing required argument")
        except Exception as e:
            # All other errors
            print(f"Error placing order: {e}")
            await ctx.send(f"Error placing order: {e}")
        print()
        print("Waiting for Discord commands...")
        print()

# Run Discord bot
if DISCORD:
    bot.run(DISCORD_TOKEN)
    print('Discord bot is running...')