# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import asyncio
import os
import sys
import traceback

try:
    import discord
    from discord.ext import commands
    from dotenv import load_dotenv

    # Custom API libraries
    from chaseAPI import *
    from fennelAPI import *
    from fidelityAPI import *
    from firstradeAPI import *
    from helperAPI import (
        ThreadHandler,
        check_package_versions,
        printAndDiscord,
        stockOrder,
        updater,
    )
    from publicAPI import *
    from robinhoodAPI import *
    from schwabAPI import *
    from tastyAPI import *
    from tradierAPI import *
    from vanguardAPI import *
    from webullAPI import *
except Exception as e:
    print(f"Error importing libraries: {e}")
    print(traceback.format_exc())
    print("Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Initialize .env file
load_dotenv()


# Global variables
SUPPORTED_BROKERS = [
    "chase",
    "fennel",
    "fidelity",
    "firstrade",
    "public",
    "robinhood",
    "schwab",
    "tastytrade",
    "tradier",
    "vanguard",
    "webull",
]
DAY1_BROKERS = [
    "chase",
    "fennel",
    "firstrade",
    "public",
    "schwab",
    "tastytrade",
    "tradier",
    "webull",
]
DISCORD_BOT = False
DOCKER_MODE = False
DANGER_MODE = False


# Account nicknames
def nicknames(broker):
    if broker in ["fid", "fido"]:
        return "fidelity"
    if broker == "ft":
        return "firstrade"
    if broker == "rh":
        return "robinhood"
    if broker == "tasty":
        return "tastytrade"
    if broker == "vg":
        return "vanguard"
    if broker == "wb":
        return "webull"
    return broker


# Runs the specified function for each broker in the list
# broker name + type of function
def fun_run(orderObj: stockOrder, command, botObj=None, loop=None):
    if command in [("_init", "_holdings"), ("_init", "_transaction")]:
        for broker in orderObj.get_brokers():
            if broker in orderObj.get_notbrokers():
                continue
            broker = nicknames(broker)
            first_command, second_command = command
            try:
                # Initialize broker
                fun_name = broker + first_command
                if broker.lower() == "fidelity":
                    # Fidelity requires docker mode argument
                    orderObj.set_logged_in(
                        globals()[fun_name](DOCKER=DOCKER_MODE), broker
                    )
                elif broker.lower() in ["fennel", "public"]:
                    # Requires bot object and loop
                    orderObj.set_logged_in(
                        globals()[fun_name](botObj=botObj, loop=loop), broker
                    )
                elif broker.lower() in ["chase", "vanguard"]:
                    fun_name = broker + "_run"
                    # PLAYWRIGHT_BROKERS have to run all transactions with one function
                    th = ThreadHandler(
                        globals()[fun_name],
                        orderObj=orderObj,
                        command=command,
                        botObj=botObj,
                        loop=loop,
                    )
                    th.start()
                    th.join()
                    _, err = th.get_result()
                    if err is not None:
                        raise Exception(
                            "Error in "
                            + fun_name
                            + ": Function did not complete successfully."
                        )
                else:
                    orderObj.set_logged_in(globals()[fun_name](), broker)

                print()
                if broker.lower() not in ["chase", "vanguard"]:
                    # Verify broker is logged in
                    orderObj.order_validate(preLogin=False)
                    logged_in_broker = orderObj.get_logged_in(broker)
                    if logged_in_broker is None:
                        print(f"Error: {broker} not logged in, skipping...")
                        continue
                    # Get holdings or complete transaction
                    if second_command == "_holdings":
                        fun_name = broker + second_command
                        globals()[fun_name](logged_in_broker, loop)
                    elif second_command == "_transaction":
                        fun_name = broker + second_command
                        globals()[fun_name](
                            logged_in_broker,
                            orderObj,
                            loop,
                        )
                        printAndDiscord(
                            f"All {broker.capitalize()} transactions complete",
                            loop,
                        )
            except Exception as ex:
                print(traceback.format_exc())
                print(f"Error in {fun_name} with {broker}: {ex}")
                print(orderObj)
            print()
        printAndDiscord("All commands complete in all brokers", loop)
    else:
        print(f"Error: {command} is not a valid command")


# Parse input arguments and update the order object
def argParser(args: list) -> stockOrder:
    args = [x.lower() for x in args]
    # Initialize order object
    orderObj = stockOrder()
    # If first argument is holdings, set holdings to true
    if args[0] == "holdings":
        orderObj.set_holdings(True)
        # Next argument is brokers
        if args[1] == "all":
            orderObj.set_brokers(SUPPORTED_BROKERS)
        elif args[1] == "day1":
            orderObj.set_brokers(DAY1_BROKERS)
        elif args[1] == "most":
            orderObj.set_brokers(list(filter(lambda x: x != 'vanguard', SUPPORTED_BROKERS)))
        elif args[1] == "fast":
            orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
        else:
            for broker in args[1].split(","):
                orderObj.set_brokers(nicknames(broker))
        # If next argument is not, set not broker
        if len(args) > 3 and args[2] == "not":
            for broker in args[3].split(","):
                if nicknames(broker) in SUPPORTED_BROKERS:
                    orderObj.set_notbrokers(nicknames(broker))
        return orderObj
    # Otherwise: action, amount, stock, broker, (optional) not broker, (optional) dry
    orderObj.set_action(args[0])
    orderObj.set_amount(args[1])
    for stock in args[2].split(","):
        orderObj.set_stock(stock)
    # Next argument is a broker, set broker
    if args[3] == "all":
        orderObj.set_brokers(SUPPORTED_BROKERS)
    elif args[3] == "day1":
        orderObj.set_brokers(DAY1_BROKERS)
    elif args[3] == "most":
        orderObj.set_brokers(list(filter(lambda x: x != 'vanguard', SUPPORTED_BROKERS)))
    elif args[3] == "fast":
        orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
    else:
        for broker in args[3].split(","):
            if nicknames(broker) in SUPPORTED_BROKERS:
                orderObj.set_brokers(nicknames(broker))
    # If next argument is not, set not broker
    if len(args) > 4 and args[4] == "not":
        for broker in args[5].split(","):
            if nicknames(broker) in SUPPORTED_BROKERS:
                orderObj.set_notbrokers(nicknames(broker))
    # If next argument is false, set dry to false
    if args[-1] == "false":
        orderObj.set_dry(False)
    # Validate order object
    orderObj.order_validate(preLogin=True)
    return orderObj


if __name__ == "__main__":
    # Determine if ran from command line
    if len(sys.argv) == 1:  # If no arguments, do nothing
        print("No arguments given, see README for usage")
        sys.exit(1)
    # Check if danger mode is enabled
    if os.getenv("DANGER_MODE", "").lower() == "true":
        DANGER_MODE = True
        print("DANGER MODE ENABLED")
        print()
    # If docker argument, run docker bot
    if sys.argv[1].lower() == "docker":
        print("Running bot from docker")
        DOCKER_MODE = DISCORD_BOT = True
    # If discord argument, run discord bot, no docker, no prompt
    elif sys.argv[1].lower() == "discord":
        updater()
        check_package_versions()
        print("Running Discord bot from command line")
        DISCORD_BOT = True
    else:  # If any other argument, run bot, no docker or discord bot
        updater()
        check_package_versions()
        print("Running bot from command line")
        print()
        cliOrderObj = argParser(sys.argv[1:])
        if not cliOrderObj.get_holdings():
            print(f"Action: {cliOrderObj.get_action()}")
            print(f"Amount: {cliOrderObj.get_amount()}")
            print(f"Stock: {cliOrderObj.get_stocks()}")
            print(f"Time: {cliOrderObj.get_time()}")
            print(f"Price: {cliOrderObj.get_price()}")
            print(f"Broker: {cliOrderObj.get_brokers()}")
            print(f"Not Broker: {cliOrderObj.get_notbrokers()}")
            print(f"DRY: {cliOrderObj.get_dry()}")
            print()
            print("If correct, press enter to continue...")
            try:
                if not DANGER_MODE:
                    input("Otherwise, press ctrl+c to exit")
                    print()
            except KeyboardInterrupt:
                print()
                print("Exiting, no orders placed")
                sys.exit(0)
        # Validate order object
        cliOrderObj.order_validate(preLogin=True)
        # Get holdings or complete transaction
        if cliOrderObj.get_holdings():
            fun_run(cliOrderObj, ("_init", "_holdings"))
        else:
            fun_run(cliOrderObj, ("_init", "_transaction"))
        sys.exit(0)

    # If discord bot, run discord bot
    if DISCORD_BOT:
        # Get discord token and channel from .env file
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception("DISCORD_TOKEN not found in .env file, please add it")
        if not os.environ["DISCORD_CHANNEL"]:
            raise Exception("DISCORD_CHANNEL not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL"))
        # Initialize discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        # Discord bot command prefix
        bot = commands.Bot(command_prefix="!", intents=intents)
        bot.remove_command("help")
        print()
        print("Discord bot is started...")
        print()

        # Bot event when bot is ready
        @bot.event
        async def on_ready():
            channel = bot.get_channel(DISCORD_CHANNEL)
            if channel is None:
                print(
                    "ERROR: Invalid channel ID, please check your DISCORD_CHANNEL in your .env file and try again"
                )
                os._exit(1)  # Special exit code to restart docker container
            await channel.send("Discord bot is started...")

        # Process the message only if it's from the specified channel
        @bot.event
        async def on_message(message):
            if message.channel.id == DISCORD_CHANNEL:
                await bot.process_commands(message)

        # Bot ping-pong
        @bot.command(name="ping")
        async def ping(ctx):
            print("ponged")
            await ctx.send("pong")

        # Help command
        @bot.command()
        async def help(ctx):
            # String of available commands
            await ctx.send(
                "Available RSA commands:\n"
                "!ping\n"
                "!help\n"
                "!rsa holdings [all|<broker1>,<broker2>,...] [not broker1,broker2,...]\n"
                "!rsa [buy|sell] [amount] [stock1|stock1,stock2] [all|<broker1>,<broker2>,...] [not broker1,broker2,...] [DRY: true|false]\n"
                "!restart"
            )

        # Main RSA command
        @bot.command(name="rsa")
        async def rsa(ctx, *args):
            discOrdObj = await bot.loop.run_in_executor(None, argParser, args)
            event_loop = asyncio.get_event_loop()
            try:
                # Validate order object
                discOrdObj.order_validate(preLogin=True)
                # Get holdings or complete transaction
                if discOrdObj.get_holdings():
                    # Run Holdings
                    await bot.loop.run_in_executor(
                        None,
                        fun_run,
                        discOrdObj,
                        ("_init", "_holdings"),
                        bot,
                        event_loop,
                    )
                else:
                    # Run Transaction
                    await bot.loop.run_in_executor(
                        None,
                        fun_run,
                        discOrdObj,
                        ("_init", "_transaction"),
                        bot,
                        event_loop,
                    )
            except Exception as err:
                print(traceback.format_exc())
                print(f"Error placing order: {err}")
                if ctx:
                    await ctx.send(f"Error placing order: {err}")

        # Restart command
        @bot.command(name="restart")
        async def restart(ctx):
            print("Restarting...")
            print()
            await ctx.send("Restarting...")
            await bot.close()
            os._exit(0)  # Special exit code to restart docker container

        # Catch bad commands
        @bot.event
        async def on_command_error(ctx, error):
            print(f"Command Error: {error}")
            await ctx.send(f"Command Error: {error}")
            # Print help command
            print("Type '!help' for a list of commands")
            await ctx.send("Type '!help' for a list of commands")

        # Run Discord bot
        bot.run(DISCORD_TOKEN)
        print("Discord bot is running...")
        print()
