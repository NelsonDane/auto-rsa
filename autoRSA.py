# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os, sys
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

# Initialize .env file
load_dotenv()

# Global variables
SUPPORTED_BROKERS = [
    "ally", "fidelity", "robinhood", "schwab", "tastytrade", "tradier"
]
DISCORD_BOT = False
DOCKER_MODE = False


# Account nicknames
def nicknames(broker):
    if broker == "rh":
        return "robinhood"
    elif broker == "tasty":
        return "tastytrade"
    else:
        return broker


# Class to hold stock order information and login objects
class stockOrder():

    def __init__(self,
                 action="NONE",
                 amount="1",
                 stock="NONE",
                 time="day",
                 price="market",
                 brokers=None,
                 notbrokers="NONE",
                 dry=True,
                 holdings=False):
        self.action = None  # Buy or sell
        self.amount = None  # Amount of shares to buy/sell
        self.stock = None  # Stock ticker
        self.time = "day"  # Only supports day for now
        self.price = "market"  # Only supports market for now
        self.brokers = []  # List of brokerages to use
        self.notbrokers = []  # List of brokerages to not use !ally
        self.dry = True  # Dry run mode
        self.holdings = False  # Get holdings from enabled brokerages
        self.logged_in = []  # List of Brokerage login objects

    # Runs the specified function for each broker in the list
    # broker name + type of function
    def fun_run(self, type, ctx=None, loop=None):
        if "all" in self.brokers:
            self.brokers = SUPPORTED_BROKERS
        if type in ["_init", "_holdings", "_transaction"]:
            for index, broker in enumerate(self.brokers):
                if broker in self.notbrokers:
                    continue
                fun_name = broker + type
                try:
                    if type == "_init":
                        if nicknames(broker) == "fidelity":
                            # Fidelity requires docker mode argument
                            self.logged_in.append(
                                globals()[fun_name](DOCKER_MODE))
                        else:
                            self.logged_in.append(globals()[fun_name]())
                    # Holdings and transaction
                    elif type == "_holdings":
                        globals()[fun_name](self.logged_in[index], ctx, loop)
                    elif type == "_transaction":
                        globals()[fun_name](self.logged_in[index], self.action,
                                            self.stock, self.amount,
                                            self.price, self.time, self.dry,
                                            ctx, loop)
                except:
                    print(traceback.format_exc())
                    print(f"Error in {fun_name} with {broker}")
                    print(self)
                print()

    def broker_login(self):
        self.fun_run("_init")

    def broker_holdings(self, ctx=None, loop=None):
        self.fun_run("_holdings", ctx, loop)

    def broker_transaction(self, ctx=None, loop=None):
        self.fun_run("_transaction", ctx, loop)

    def __str__(self) -> str:
        return f"Self: \n \
                Action: {self.action}\n \
                Amount: {self.amount}\n \
                Stock: {self.stock}\n \
                Time: {self.time}\n \
                Price: {self.price}\n \
                Brokers: {self.brokers}\n \
                Not Brokers: {self.notbrokers}\n \
                Dry: {self.dry}\n \
                Holdings: {self.holdings}\n \
                Logged In: {self.logged_in}"


# Regex function to check if stock ticker is valid
def isStockTicker(symbol):
    pattern = r'^[A-Z]{1,5}$'  # Regex pattern for stock tickers
    return (re.match(pattern, symbol))


# Parse input arguments and update the order object
def argParser(args):
    docker = False
    orderObj = stockOrder()
    for arg in args:
        arg = arg.lower()
        if "docker" == arg:
            docker = True
            print("Running in docker mode")
        # Exclusions
        elif arg in ["not", "but", "except", "exclude", "excluding"]:
            next_arg = nicknames(args[args.index(arg) + 1]).split(",")
            for broker in next_arg:
                if broker in SUPPORTED_BROKERS:
                    orderObj.notbrokers.append(broker)
        elif arg in ["buy", "sell"]:
            orderObj.action = arg
        elif arg.isnumeric():
            orderObj.amount = int(arg)
        elif arg == "false":
            orderObj.dry = False
        # Check nicknames, or if all, and not in notbrokers
        elif (nicknames(arg.split(",")[0]) in SUPPORTED_BROKERS
              or arg == "all") and (nicknames(arg.split(",")[0])
                                    not in orderObj.notbrokers):
            for broker in arg.split(","):
                orderObj.brokers.append(nicknames(broker))
        elif arg == "holdings":
            orderObj.holdings = True
        elif isStockTicker(arg.upper()) and arg.lower(
        ) != "dry" and orderObj.stock is None:
            orderObj.stock = arg.upper()
    return orderObj, docker


if __name__ == "__main__":
    # Determine if ran from command line
    if len(sys.argv) == 1:  # If no arguments, run discord bot, no docker
        print("Running Discord bot from command line")
        DISCORD_BOT = True
    elif len(
            sys.argv
    ) == 2 and sys.argv[1] == "docker":  # If docker argument, run docker bot
        print("Running bot from docker")
        DOCKER_MODE = True
        DISCORD_BOT = True
    else:  # If any other argument, run bot, no docker or discord bot
        print("Running bot from command line")
        orderObj = argParser(sys.argv[1:])[0]
        if not orderObj.holdings:
            print(f"Action: {orderObj.action}")
            print(f"Amount: {orderObj.amount}")
            print(f"Stock: {orderObj.stock}")
            print(f"Time: {orderObj.time}")
            print(f"Price: {orderObj.price}")
            print(f"Broker: {orderObj.brokers}")
            print(f"Not Broker: {orderObj.notbrokers}")
            print(f"DRY: {orderObj.dry}")
            print()
            print("If correct, press enter to continue...")
            try:
                input("Otherwise, press ctrl+c to exit")
                print()
            except KeyboardInterrupt:
                print()
                print("Exiting, no orders placed")
                sys.exit(0)
        orderObj.broker_login()
        if orderObj.holdings:
            orderObj.broker_holdings()
        else:
            orderObj.broker_transaction()
        # Kill selenium drivers
        if "fidelity" in [n.lower() for n in orderObj.brokers]:
            killDriver(orderObj.logged_in[orderObj.brokers.index("fidelity")])
        sys.exit(0)

    if DISCORD_BOT:
        # Get discord token and channel from .env file, setting channel to None if not found
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception(
                "DISCORD_TOKEN not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL", None)
        if DISCORD_CHANNEL:
            DISCORD_CHANNEL = int(DISCORD_CHANNEL)
        # Initialize discord bot
        intents = discord.Intents.all(
        )  # TODO: Change this to only the intents we need
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
            await ctx.send(
                '!rsa [buy|sell] [amount] [stock] [all|ally|robinhood/rh|schwab|tradier] [DRY/true/false]'
            )
            await ctx.send('!restart')

        # Main RSA command
        @bot.command(name='rsa')
        async def rsa(ctx, *args):
            orderObj = (await bot.loop.run_in_executor(None, argParser,
                                                       args))[0]
            loop = asyncio.get_event_loop()
            try:
                await bot.loop.run_in_executor(None, orderObj.broker_login)
                if orderObj.holdings:
                    await bot.loop.run_in_executor(None,
                                                   orderObj.broker_holdings,
                                                   ctx, loop)
                else:
                    await bot.loop.run_in_executor(None,
                                                   orderObj.broker_transaction,
                                                   ctx, loop)
            except Exception as e:
                print(f"Error placing order on {orderObj.name}: {e}")
                if ctx:
                    await ctx.send(
                        f"Error placing order on {orderObj.name}: {e}")

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
