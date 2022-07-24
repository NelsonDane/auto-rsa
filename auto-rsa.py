# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import sys
from time import sleep
import discord
from discord.ext import commands
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
    wanted_amount = int(sys.argv[2])
    wanted_stock = sys.argv[3]
    wanted_time = "day" # Only supports day for now
    wanted_price = "market" # Only supports market for now
    # Check if DRY mode is enabled
    print(sys.argv[4])
    #sleep(100)
    # if sys.argv[4].lower() == "dry" and not (sys.argv[4].lower() in brokerages):
    #     print("here")
    # sleep(100)
    if (sys.argv[4].lower()) == "dry" and not (sys.argv[4].lower() in brokerages):
        print("here")
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
    print(f"DRY: {DRY}")
    print(f"Broker: {single_broker}")

sleep(100)
# Initialize .env file
load_dotenv()

# Get discord token and prefix from .env file, setting to None if not found
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN:
    DISCORD = True
else:
    DISCORD = False

# Raise error if no command line arguments and no discord token
if len(sys.argv) == 1 and not DISCORD:
    print("Error: No command line arguments and no discord token")
    sys.exit(1)

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

# # Buy/Sell stock on each account if "all"
# # Shut up, grammar is important smh
if wanted_amount > 1:
    grammar = "shares"
else:
    grammar = "share"
print("==========================================================")
print(f"Order: {wanted_action} {wanted_amount} {grammar} of {wanted_stock} on {single_broker}")
print("==========================================================")
print()
if single_broker == "all":
    # Ally
    ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
    # Robinhood
    robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
    # Schwab
    schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
    # Webull
    webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
    # Tradier
    tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
elif single_broker == "ally":
    # Ally
    ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
elif single_broker == "fidelity":
    # Fidelity
    #fidelity_transaction(fidelity_user, fidelity_password, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
    print("bruh")
elif single_broker == "robinhood":
    # Robinhood
    robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
elif single_broker == "schwab":
    # Schwab
    schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
elif single_broker == "webull":
    # Webull
    webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
elif single_broker == "tradier":
    # Tradier
    tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
else:
    print("Error: Invalid broker")
    sys.exit(1)

if DISCORD:
    # Run bot
    bot.run(DISCORD_TOKEN)
    print('Discord bot is running...')