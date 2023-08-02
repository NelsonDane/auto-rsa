# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import re
import sys

try:
    import discord
    from discord.ext import commands
    from dotenv import load_dotenv

    # Custom API libraries
    from allyAPI import *
    from fidelityAPI import *
    from helperAPI import *
    from robinhoodAPI import *
    from schwabAPI import *
    from tastyAPI import *
    from tradierAPI import *
except Exception as e:
    print(f"Error importing libraries: {e}")
    print("Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Initialize .env file
load_dotenv()


# Global variables
SUPPORTED_BROKERS = ["ally", "fidelity", "robinhood", "schwab", "tastytrade", "tradier"]
DISCORD_BOT = False
DOCKER_MODE = False
SUPRESS_OLD_WARN = False


# Account nicknames
def nicknames(broker):
    if broker == "rh":
        return "robinhood"
    if broker == "tasty":
        return "tastytrade"
    return broker


# Class to hold stock order information and login objects
class stockOrder:
    def __init__(self):
        self.action = None  # Buy or sell
        self.amount = None  # Amount of shares to buy/sell
        self.stock = []  # List of stock tickers to buy/sell
        self.time = "day"  # Only supports day for now
        self.price = "market"  # Only supports market for now
        self.brokers = []  # List of brokerages to use
        self.notbrokers = []  # List of brokerages to not use !ally
        self.dry = True  # Dry run mode
        self.holdings = False  # Get holdings from enabled brokerages
        self.logged_in = []  # List of Brokerage objects

    # Runs the specified function for each broker in the list
    # broker name + type of function
    def fun_run(self, command, ctx=None, loop=None):
        if command in ["_init", "_holdings", "_transaction"]:
            for index, broker in enumerate(self.brokers):
                if broker in self.notbrokers:
                    continue
                fun_name = broker + command
                try:
                    if command == "_init":
                        if nicknames(broker) == "fidelity":
                            # Fidelity requires docker mode argument
                            self.logged_in.append(globals()[fun_name](DOCKER=DOCKER_MODE))
                        else:
                            self.logged_in.append(globals()[fun_name]())
                    # Holdings and transaction
                    elif self.logged_in[index] is None:
                        print(f"Error: {broker} not logged in, skipping...")
                    elif command == "_holdings":
                        globals()[fun_name](self.logged_in[index], ctx, loop)
                    elif command == "_transaction":
                        globals()[fun_name](
                            self.logged_in[index],
                            self.action,
                            self.stock,
                            self.amount,
                            self.price,
                            self.time,
                            self.dry,
                            ctx,
                            loop,
                        )
                except Exception as ex:
                    print(traceback.format_exc())
                    print(f"Error in {fun_name} with {broker}: {ex}")
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
    pattern = r"^[A-Z]{1,5}$"  # Regex pattern for stock tickers
    return re.match(pattern, symbol)


# Parse input arguments and update the order object
def argParser(args):
    orderObj = stockOrder()
    for arg in args:
        arg = arg.lower()
        # Exclusions
        if arg == "not":
            next_arg = nicknames(args[args.index(arg) + 1]).split(",")
            for broker in next_arg:
                if nicknames(broker) in SUPPORTED_BROKERS:
                    orderObj.notbrokers.append(nicknames(broker))
        elif arg in ["buy", "sell"]:
            orderObj.action = arg
        elif arg.isnumeric():
            orderObj.amount = int(arg)
        elif arg == "false":
            orderObj.dry = False
        # If first item of list is a broker, it must be a list of brokers
        elif nicknames(arg.split(",")[0]) in SUPPORTED_BROKERS:
            for broker in arg.split(","):
                # Add broker if it is valid and not in notbrokers
                if (
                    nicknames(broker) in SUPPORTED_BROKERS
                    and nicknames(broker) not in orderObj.notbrokers
                ):
                    orderObj.brokers.append(nicknames(broker))
        elif arg == "all":
            if "all" not in orderObj.brokers and orderObj.brokers == []:
                orderObj.brokers = SUPPORTED_BROKERS
        elif arg == "holdings":
            orderObj.holdings = True
        # If first item of list is a stock, it must be a list of stocks
        elif (
            isStockTicker(arg.split(",")[0].upper())
            and arg.lower() != "dry"
            and orderObj.stock == []
        ):
            for stock in arg.split(","):
                orderObj.stock.append(stock.upper())
    # Remove duplicates
    orderObj.brokers = list(dict.fromkeys(orderObj.brokers))
    orderObj.notbrokers = list(dict.fromkeys(orderObj.notbrokers))
    orderObj.stock = list(dict.fromkeys(orderObj.stock))
    # Remove notbrokers from brokers
    for broker in orderObj.notbrokers:
        if broker in orderObj.brokers:
            orderObj.brokers.remove(broker)
    return orderObj


if __name__ == "__main__":
    # Check for legacy .env file format
    # This should be removed in a future release
    if os.getenv("SUPRESS_OLD_WARN", "").lower() == "true":
        SUPRESS_OLD_WARN = True
    if re.search(r"(_USERNAME|_PASSWORD)", str(os.environ)) and not SUPRESS_OLD_WARN:
        print("Legacy .env file found. Please update to new format.")
        print("See .env.example for details.")
        print("To supress this warning, set SUPRESS_OLD_WARN=True in .env")
        # Print troublesome variables
        print("Please update/remove the following variables:")
        for key in os.environ:
            if re.search(r"(_USERNAME|_PASSWORD)", key):
                print(f"{key}={os.environ[key]}")
        sys.exit(1)
    # Determine if ran from command line
    if len(sys.argv) == 1:  # If no arguments, do nothing
        print("No arguments given, see README for usage")
        sys.exit(1)
    elif (
        len(sys.argv) == 2 and sys.argv[1].lower() == "docker"
    ):  # If docker argument, run docker bot
        print("Running bot from docker")
        DOCKER_MODE = DISCORD_BOT = True
    elif (
        len(sys.argv) == 2 and sys.argv[1].lower() == "discord"
    ):  # If discord argument, run discord bot, no docker, no prompt
        print("Running Discord bot from command line")
        DISCORD_BOT = True
    else:  # If any other argument, run bot, no docker or discord bot
        print("Running bot from command line")
        cliOrderObj = argParser(sys.argv[1:])
        if not cliOrderObj.holdings:
            print(f"Action: {cliOrderObj.action}")
            print(f"Amount: {cliOrderObj.amount}")
            print(f"Stock: {cliOrderObj.stock}")
            print(f"Time: {cliOrderObj.time}")
            print(f"Price: {cliOrderObj.price}")
            print(f"Broker: {cliOrderObj.brokers}")
            print(f"Not Broker: {cliOrderObj.notbrokers}")
            print(f"DRY: {cliOrderObj.dry}")
            print()
            print("If correct, press enter to continue...")
            try:
                input("Otherwise, press ctrl+c to exit")
                print()
            except KeyboardInterrupt:
                print()
                print("Exiting, no orders placed")
                sys.exit(0)
        cliOrderObj.broker_login()
        if cliOrderObj.holdings:
            cliOrderObj.broker_holdings()
        else:
            cliOrderObj.broker_transaction()
        # Kill selenium drivers
        for obj in cliOrderObj.logged_in:
            if obj is not None and obj.get_name().lower() == "fidelity":
                killDriver(obj)
        sys.exit(0)

    if DISCORD_BOT:
        # Get discord token and channel from .env file
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception("DISCORD_TOKEN not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL", None)
        if DISCORD_CHANNEL:
            DISCORD_CHANNEL = int(DISCORD_CHANNEL)
        # Initialize discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        # Discord bot command prefix
        bot = commands.Bot(command_prefix="!", intents=intents)
        bot.remove_command("help")
        print()
        print("Discord bot is started...")
        print()

        # String of available commands
        help_string = (
            "Available commands:\n"
            "!ping\n"
            "!help\n"
            "!rsa holdings [all|<broker1>,<broker2>,...]\n"
            "!rsa [buy|sell] [amount] [stock] [all|<broker1>,<broker2>,...] [not <broker1>,<broker2>,...] [DRY: true|false]\n"
            "!restart"
        )

        # Bot event when bot is ready
        if DISCORD_CHANNEL:

            @bot.event
            async def on_ready():
                channel = bot.get_channel(DISCORD_CHANNEL)
                await channel.send("Discord bot is started...")
                # Old .env file format warning
                if not SUPRESS_OLD_WARN:
                    await channel.send("Heads up! .env file format has changed, see .env.example for new format")
                    await channel.send("To supress this message, set SUPRESS_OLD_WARN to True in your .env file")

        # Bot ping-pong
        @bot.command(name="ping")
        async def ping(ctx):
            print("ponged")
            await ctx.send("pong")

        # Help command
        @bot.command()
        async def help(ctx):
            await ctx.send(help_string)

        # Main RSA command
        @bot.command(name="rsa")
        async def rsa(ctx, *args):
            discOrdObj = (await bot.loop.run_in_executor(None, argParser, args))
            loop = asyncio.get_event_loop()
            try:
                await bot.loop.run_in_executor(None, discOrdObj.broker_login)
                if discOrdObj.holdings:
                    await bot.loop.run_in_executor(
                        None, discOrdObj.broker_holdings, ctx, loop
                    )
                else:
                    await bot.loop.run_in_executor(
                        None, discOrdObj.broker_transaction, ctx, loop
                    )
            except Exception as err:
                print(f"Error placing order on {discOrdObj.name}: {err}")
                if ctx:
                    await ctx.send(f"Error placing order on {discOrdObj.name}: {err}")

        # Restart command
        @bot.command(name="restart")
        async def restart(ctx):
            print("Restarting...")
            print()
            await ctx.send("Restarting...")
            await bot.close()
            os._exit(0)

        # Catch bad commands
        @bot.event
        async def on_command_error(ctx, error):
            print(f"Error: {error}")
            await ctx.send(f"Error: {error}")
            # Print help command
            await ctx.send(help_string)

        # Run Discord bot
        bot.run(DISCORD_TOKEN)
        print("Discord bot is running...")
        print()
