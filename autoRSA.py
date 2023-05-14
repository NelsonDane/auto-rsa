# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import sys
import re
import discord
from discord.ext import commands
from dotenv import load_dotenv
# Custom API libraries
from allyAPI import *
from robinhoodAPI import *
from fidelityAPI import *
from schwabAPI import *
from tastyAPI import *
from tradierAPI import *

supported_brokerages = ["ally", "fidelity", "robinhood", "schwab", "tastytrade", "tradier"]

# Initialize .env file
load_dotenv()

# Global variables
discord_bot = False
docker_mode = False

# Account nicknames
async def nicknames(broker):
    if broker == "rh":
        return "robinhood"
    elif broker == "tasty":
        return "tastytrade"
    else:
        return broker
    
# Class to hold stock order information and login objects
class stockOrder():
    def __init__(self, action="NONE", amount="1", stock="NONE", time="day", price="market", brokers=None, notbrokers="NONE", dry=True, holdings=False):
        self.action = None # Buy or sell
        self.amount = None # Amount of shares to buy/sell
        self.stock = None # Stock ticker
        self.time = "day" # Only supports day for now
        self.price = "market" # Only supports market for now
        self.brokers = [] # List of brokerages to use
        self.notbrokers = [] # List of brokerages to not use !ally
        self.dry = True # Dry run mode
        self.holdings = False # Get holdings from enabled brokerages
        self.logged_in = [] # List of Brokerage login objects
                
    # Runs the specified function for each broker in the list
    # broker name + type of function
    async def fun_run(self, type, ctx=None):
        if "all" in self.brokers:
            self.brokers = supported_brokerages
        if type in ["_init", "_holdings", "_transaction"]:
            for index, broker in enumerate(self.brokers):
                if broker in self.notbrokers:
                    continue
                fun_name = broker + type
                try:
                    if type == "_init": 
                        if await nicknames(broker) == "fidelity":
                            self.logged_in.append(await globals()[fun_name](docker_mode)) # Fidelity requires docker mode argument
                        else:
                            self.logged_in.append(await globals()[fun_name]())
                    else:
                        await globals()[fun_name](self.logged_in[index], ctx)
                except:
                    print(traceback.format_exc())
                    print(f"Error: {fun_name} not found in fun_run {type}")
                print()

    async def broker_login(self):            
            await self.fun_run("_init")

    async def broker_holdings(self, ctx=None):
            await self.fun_run("_holdings", ctx)

    async def broker_transaction(self, ctx=None):
            await self.fun_run("_transaction")

    def __str__(self) -> str:
        return f"Action: {self.action}\nAmount: {self.amount}\nStock: {self.stock}\nTime: {self.time}\nPrice: {self.price}\nBrokers: {self.brokers}\nNot Brokers: {self.notbrokers}\nDry: {self.dry}\nHoldings: {self.holdings}\nLogged In: {self.logged_in}"

# Regex function to check if stock ticker is valid
async def isStockTicker(symbol):
    pattern = r'^[A-Z]{1,5}$' # Regex pattern for stock tickers
    return(re.match(pattern, symbol))

# Parse input arguments and update the order object
async def argParser(args, ctx=None):
    docker = False
    orderObj = stockOrder()
    for arg in args:
        arg = arg.lower()
        if "docker" == arg:
            docker = True
            print("Running in docker mode")
        if arg in ["buy", "sell"]:
            orderObj.action = arg
        if arg.isnumeric():
            orderObj.amount = int(arg)
        if await isStockTicker(arg):
            orderObj.stock = arg
        if await nicknames(arg) in supported_brokerages or arg == "all":
            orderObj.brokers.append(await nicknames(arg))
        if arg == "dry" or arg == "true":
            orderObj.dry = True
        if arg[0] == "!":
            orderObj.notbrokers.append(arg[1:])
        if arg == "holdings":
            orderObj.holdings = True
    return orderObj, docker

if __name__ == "__main__":
    # Determine if ran from command line
    if len(sys.argv) == 1: # If no arguments, run discord bot, no docker
        print("Running Discord bot from command line")
        discord_bot = True
    elif len(sys.argv) == 2 and sys.argv[1] == "docker": # If docker argument, run docker bot
        print("Running bot from docker")
        docker_mode = True
        discord_bot = True
    else: # If any other argument, run bot, no docker or discord bot
        print("Running bot from command line")
        orderObj = asyncio.run(argParser(sys.argv[1:]))[0]
        asyncio.run(orderObj.broker_login())
        if orderObj.holdings:
            asyncio.run(orderObj.broker_holdings())
            sys.exit()
        else:
            asyncio.run(orderObj.broker_transaction())
            sys.exit()

    if discord_bot:
        # Get discord token and channel from .env file, setting channel to None if not found
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception("DISCORD_TOKEN not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL", None)
        if DISCORD_CHANNEL:
            DISCORD_CHANNEL = int(DISCORD_CHANNEL)
        # Initialize discord bot
        intents = discord.Intents.all() # TODO: Change this to only the intents we need
        # Discord bot command prefix
        bot = commands.Bot(command_prefix='!', intents=intents)
        bot.remove_command('help')
        print()
        print('Discord bot is started...')
        print()

        # Bot event when bot is ready
        if DISCORD_CHANNEL:
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
            await ctx.send('!holdings [all|ally|robinhood/rh|schwab|tradier]')
            await ctx.send('!rsa [buy|sell] [amount] [stock] [all|ally|robinhood/rh|schwab|tradier] [DRY/true/false]')
            await ctx.send('!restart')
            
        # Main RSA command
        @bot.command(name='rsa')
        async def rsa(ctx, *args):
            orderObj = (await argParser(args))[0]
            try:
                await orderObj.broker_login()
                await orderObj.broker_transaction(ctx)
            except Exception as e:
                print(f"Error placing order on {orderObj.name}: {e}")
                if ctx:
                    await ctx.send(f"Error placing order on {orderObj.name}: {e}")
            
        # Holdings command
        @bot.command(name='holdings')
        async def holdings(ctx, *args):
            orderObj = (await argParser(args))[0]
            orderObj.holdings = True
            try:
                await orderObj.broker_login()
                await orderObj.broker_holdings(ctx)
            except Exception as e:
                print(f"Error getting holdings: {e}")
                await ctx.send(f"Error getting holdings: {e}")

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
        print()
