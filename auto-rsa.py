# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import sys
from datetime import datetime
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
# Custom API libraries
from allyAPI import *
from fidelityAPI import *
from robinhoodAPI import *
from schwabAPI import *
from webullAPI import *
from tradierAPI import *

# List of supported and enabled brokerages
supported_brokerages = ["all", "ally", "robinhood", "rh", "schwab", "tradier"]
enabled_brokerages = []

# Initialize .env file
load_dotenv()

# Get stock info from command line arguments
if len(sys.argv) > 1 and sys.argv[1] != "holdings":
    wanted_action = sys.argv[1].lower()
    try:
        wanted_amount = int(sys.argv[2])
    except:
        if sys.argv[2] is type (str) and sys.argv[2] == "all":
            wanted_amount = "all"
        else:
            print("Error: Invalid amount")
            sys.exit(1)
    wanted_stock = sys.argv[3].upper()
    wanted_time = "day" # Only supports day for now
    wanted_price = "market" # Only supports market for now
    # Check if DRY mode is enabled   
    if (sys.argv[4].lower()) == "dry" and not (sys.argv[4].lower() in supported_brokerages):
        DRY = True
        single_broker = "all"
        enabled_brokerages.append(single_broker)
    elif sys.argv[4].lower() in supported_brokerages:
        single_broker = sys.argv[4].lower()
        enabled_brokerages.append(single_broker)
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
    print()
    cli_mode = True
    should_get_holdings = False
elif len(sys.argv) == 3 and sys.argv[1] == "holdings":
    single_broker = sys.argv[2].lower()
    enabled_brokerages.append(single_broker)
    should_get_holdings = True
    cli_mode = True
else:
    cli_mode = False
    should_get_holdings = False

# Get discord token and prefix from .env file, setting to None if not found
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL", None)
if DISCORD_TOKEN and not cli_mode:
    DISCORD = True
    if DISCORD_CHANNEL:
        DISCORD_CHANNEL = int(DISCORD_CHANNEL)
else:
    DISCORD = False
    DISCORD_CHANNEL = None
    ctx = None

# Raise error if no command line arguments and no discord token
if (not cli_mode) and (not should_get_holdings) and (not DISCORD):
    print("Error: No command line arguments and no discord token")
    sys.exit(1)
elif (not cli_mode) and (not should_get_holdings) and DISCORD:
    single_broker = "all"
    enabled_brokerages.append(single_broker)
    wanted_time = "day"
    wanted_price = "market"

# Initialize Accounts
if single_broker == "all":
    print("==========================================================")
    print("Initializing Accounts...")
    print("==========================================================")
    print()
    ally_account = ally_init()
    if ally_account is not None:
        enabled_brokerages.append("ally")
    print()
    # fidelity_account = fidelity_init()
    # if fidelity_account is not None:
    #     enabled_brokerages.append("fidelity")
    #print()
    robinhood = robinhood_init()
    if robinhood is not None:
        enabled_brokerages.append("robinhood")
        enabled_brokerages.append("rh")
    print()
    schwab = schwab_init()
    if schwab is not None:
        enabled_brokerages.append("schwab")
    print()
    # webull_account = webull_init()
    # if webull_account is not None:
    #     enabled_brokerages.append("webull")
    #     enabled_brokerages.append("wb")
    # print()
    tradier = tradier_init()
    if tradier is not None:
        enabled_brokerages.append("tradier")
    print()
elif single_broker == "ally":
    ally_account = ally_init()
    if ally_account is not None:
        enabled_brokerages.append("ally")
    print()
elif single_broker == "fidelity":
    fidelity_account = fidelity_init()
    if fidelity_account is not None:
        enabled_brokerages.append("fidelity")
elif single_broker == "robinhood" or single_broker == "rh":
    robinhood = robinhood_init()
    if robinhood is not None:
        enabled_brokerages.append("robinhood")
        enabled_brokerages.append("rh")
    print()
elif single_broker == "schwab":
    schwab = schwab_init()
    if schwab is not None:
        enabled_brokerages.append("schwab")
    print()
elif single_broker == "webull" or single_broker == "wb":
    webull_account = webull_init()
    if webull_account is not None:
        enabled_brokerages.append("webull")
        enabled_brokerages.append("wb")
    print()
elif single_broker == "tradier":
    tradier = tradier_init()
    if tradier is not None:
        enabled_brokerages.append("tradier")
    print()
else:
    print("Error: Invalid broker")
    sys.exit(1)

if DISCORD:
    print("Waiting for Discord commands...")
    print()

async def isMarketHours(timeUntil=False,ctx=None):
    # Get current time and open/close times
    now = datetime.now()
    MARKET_OPEN = now.replace(hour=9, minute=30)
    MARKET_CLOSE = now.replace(hour=16, minute=0)
    # Check if market is open
    if not timeUntil:
        # Check if market is open
        if MARKET_OPEN < now < MARKET_CLOSE:
            return True
        else:
            return False
    else:
        # Get time until market open, or until market close
        if MARKET_OPEN < now < MARKET_CLOSE:
            close_seconds = (MARKET_CLOSE - now).total_seconds()
            close_hours = int(divmod(close_seconds, 3600)[0])
            close_minutes = int(divmod(close_seconds, 60)[0]) - close_hours * 60
            print(f"Market is open, closing in {close_hours} hours and {close_minutes} minutes")
            if ctx:
                await ctx.send(f"Market is open, closing in {close_hours} hours and {close_minutes} minutes")
        else:
            open_seconds = (MARKET_OPEN - now).total_seconds()
            open_hours = int(divmod(open_seconds, 3600)[0])
            open_minutes = int(divmod(open_seconds, 60)[0]) - open_hours * 60
            print(f"Market is closed, opening in {open_hours} hours and {open_minutes} minutes")
            if ctx:
                await ctx.send(f"Market is closed, opening in {open_hours} hours and {open_minutes} minutes")

async def get_holdings(account, ctx=None):
    account = account.lower()
    if account in enabled_brokerages:
        try:
            if account == "ally" or account == "all":
                await ally_holdings(ally_account, ctx)
        except:
            pass
        # if account == "fidelity" or account == "all":
        #     #await fidelity_get_holdings()
        #     pass
        try:
            if account == "robinhood" or account == "rh" or account == "all":
                await robinhood_holdings(robinhood, ctx)
        except:
            pass
        try:
            if account == "schwab" or account == "all":
                await schwab_holdings(schwab, ctx)
        except:
            pass
        # if account == "webull" or account == "wb" or account == "all":
        #     await webull_holdings(webull_account, ctx)
        try:
            if account == "tradier" or account == "all":
                await tradier_holdings(tradier, ctx)
        except:
            pass
    else:
        print("Error: Invalid broker")

async def place_order(wanted_action, wanted_amount, wanted_stock, single_broker, DRY=True, ctx=None):
    if await isMarketHours():
        try:
            # Input validation
            wanted_action = wanted_action.lower()
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
                # await webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
                # Tradier
                await tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            elif single_broker == "ally":
                # Ally
                await ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # elif single_broker == "fidelity":
            #     # Fidelity
            #     #fidelity_transaction(fidelity_user, fidelity_password, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY)
            #     print()
            elif single_broker == "robinhood" or single_broker == "rh":
                # Robinhood
                await robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            elif single_broker == "schwab":
                # Schwab
                #print("bruh")
                await schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            # elif single_broker == "webull" or single_broker == "wb":
            #     # Webull
            #     await webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            elif single_broker == "tradier":
                # Tradier
                await tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amount, wanted_price, wanted_time, DRY, ctx)
            else:
                # Invalid broker
                print("Error: Invalid broker")
                if ctx:
                    await ctx.send("Error: Invalid broker")
        except Exception as e:
            print(f"Error placing order: {e}")  
            await ctx.send(f"Error placing order: {e}")
    else:
        print("Unable to place order: Market is closed")
        if ctx:
            await ctx.send("Unable to place order: Market is closed")

# If getting holdings, get them
if cli_mode and should_get_holdings and (not DISCORD):
    try:
        asyncio.run(get_holdings(single_broker))
        sys.exit(0)
    except Exception as e:
        print(f"Error getting holdings: {e}")
        sys.exit(1)
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
    # Bot intents
    intents = discord.Intents.all()
    # Discord bot command prefix
    bot = commands.Bot(command_prefix='!', intents=intents)
    bot.remove_command('help')
    print()
    print('Discord bot is started...')
    print()

    # Bot event when bot is ready
    if DISCORD_CHANNEL is not None:
        @bot.event
        async def on_ready():
            channel = bot.get_channel(DISCORD_CHANNEL)
            await channel.send('Discord bot is started...')

    # Bot ping-pong
    @bot.command(name='ping')
    async def ping(ctx):
        print('ponged')
        await ctx.send('pong')

    # Help command
    @bot.command()
    async def help(ctx):
        await ctx.send('Available commands:')
        await ctx.send('!ping')
        await ctx.send('!help')
        await ctx.send('!market_hours, !market')
        await ctx.send('!holdings [all|ally|robinhood/rh|schwab|tradier]')
        await ctx.send('!rsa [buy|sell] [amount] [stock] [all|ally|robinhood/rh|schwab|tradier] [DRY/true/false]')
        await ctx.send('!restart')

    # Print time until market open or close
    @bot.command(aliases=['market_hours'])
    async def market(ctx):
        await isMarketHours(True, ctx)
        print()
        print("Waiting for Discord commands...")
        print()
    
    # Main RSA command
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
    
    # Holdings command
    @bot.command(name='holdings')
    async def holdings(ctx, broker):
        try:
            await get_holdings(broker, ctx)
        except Exception as e:
            print(f"Error getting holdings: {e}")
            await ctx.send(f"Error getting holdings: {e}")
        print()
        print("Waiting for Discord commands...")
        print()

    # Restart command
    @bot.command(name='restart')
    async def restart(ctx):
        print("Restarting...")
        print()
        await ctx.send("Restarting...")
        await bot.close()
        os._exit(0)

    # Run Discord bot
    bot.run(DISCORD_TOKEN)
    print('Discord bot is running...')