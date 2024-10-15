# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import asyncio
import os
import sys
import traceback

# Check Python version (minimum 3.10)
print("Python version:", sys.version)
if sys.version_info < (3, 10):
    print("ERROR: Python 3.10 or newer is required")
    sys.exit(1)
print()

try:
    import discord
    from discord.ext import commands
    from discord.app_commands import user_install
    from dotenv import load_dotenv

    # Custom API libraries
    from bbaeAPI import *
    from chaseAPI import *
    from dspacAPI import *
    from fennelAPI import *
    from fidelityAPI import *
    from firstradeAPI import *
    from helperAPI import (
        ThreadHandler,
        check_package_versions,
        printAndDiscord,
        stockOrder,
        updater,
        set_discord_bot_instance
    )
    from publicAPI import *
    from robinhoodAPI import *
    from schwabAPI import *
    from tastyAPI import *
    from tornadoAPI import *
    from tradierAPI import *
    from vanguardAPI import *
    from webullAPI import *
    from wellsfargoAPI import *
except Exception as e:
    print(f"Error importing libraries: {e}")
    print(traceback.format_exc())
    print("Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Initialize .env file
load_dotenv()


# Global variables
SUPPORTED_BROKERS = [
    "bbae",
    "chase",
    "dspac",
    "fennel",
    "fidelity",
    "firstrade",
    "public",
    "robinhood",
    "schwab",
    "tastytrade",
    "tornado",
    "tradier",
    "vanguard",
    "webull",
    "wellsfargo",
]
DAY1_BROKERS = [
    "bbae",
    "chase",
    "dspac",
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
    if broker == "bb":
        return "bbae"
    if broker == "ds":
        return "dspac"
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
    if broker == "wf":
        return "wellsfargo"
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
                if broker.lower() == "wellsfargo":
                    # Fidelity requires docker mode argument
                    orderObj.set_logged_in(
                        globals()[fun_name](
                            DOCKER=DOCKER_MODE, botObj=botObj, loop=loop
                        ),
                        broker,
                    )
                elif broker.lower() == "tornado":
                    # Requires docker mode argument and loop
                    orderObj.set_logged_in(
                        globals()[fun_name](DOCKER=DOCKER_MODE, loop=loop),
                        broker,
                    )

                elif broker.lower() in [
                    "bbae",
                    "dspac",
                    "fennel",
                    "firstrade",
                    "public",
                ]:
                    # Requires bot object and loop
                    orderObj.set_logged_in(
                        globals()[fun_name](botObj=botObj, loop=loop), broker
                    )
                elif broker.lower() in ["chase", "fidelity", "vanguard"]:
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
                if broker.lower() not in ["chase", "fidelity", "vanguard"]:
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


# No longer used for Discord bot version
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
            orderObj.set_brokers(
                list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS))
            )
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
        if stock != "":
            orderObj.set_stock(stock)
    # Next argument is a broker, set broker
    if args[3] == "all":
        orderObj.set_brokers(SUPPORTED_BROKERS)
    elif args[3] == "day1":
        orderObj.set_brokers(DAY1_BROKERS)
    elif args[3] == "most":
        orderObj.set_brokers(list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS)))
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
        # Get discord token from .env file
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception("DISCORD_TOKEN not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        # Initialize discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        # Discord bot command prefix
        bot = commands.Bot(command_prefix="!", intents=intents)
        print()

        # Bot event when bot is ready
        @bot.event
        async def on_ready():
            print(f"Discord bot is started as {bot.user.name}...")
            print(f"Owner User: {bot.application.owner.name}")
            set_discord_bot_instance(bot)
            print()
            try:
                await bot.tree.sync()
                print("Commands synchronized successfully.")
            except Exception as sync_e:
                print(f"Error syncing commands: {sync_e}")

        # Bot ping-pong
        @bot.tree.command(name="ping", description="pinger ponger")
        @user_install
        async def ping(interaction: discord.Interaction):
            await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
            print("ponged")
            await bot.application.owner.send(content=f"PONG!\nHello! I am {bot.user.name}, you can run your commands in our DMs or in a server!")
            await interaction.followup.send("pong", ephemeral=interaction.guild is not None)

        # Help command
        @bot.tree.command(name="help", description="List all available commands")
        @user_install
        async def help(interaction: discord.Interaction):
            await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
            # String of available commands
            print("helped")
            await interaction.followup.send(
                "Available RSA commands:\n"
                "/help\n"
                "/ping\n"
                "/holdings [all|<broker1>,<broker2>,...] [not broker1,broker2,...]\n"
                "/transaction [buy|sell] [amount] [stock1|stock1,stock2] [all|<broker1>,<broker2>,...] [not broker1,broker2,...] [DRY: true|false]\n"
                "/restart", ephemeral=interaction.guild is not None
            )

        # New holdings command
        @bot.tree.command(name="holdings", description="Get holdings for specified brokers")
        @user_install
        async def holdings(
            interaction: discord.Interaction,
            brokers: str,
            not_brokers: str = None
        ):
            try:
                await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
                await interaction.followup.send("Checking holdings, you will be DMed shortly!", ephemeral=interaction.guild is not None)
                orderObj = stockOrder()
                orderObj.set_holdings(True)
                # Set brokers
                if brokers == "all":
                    orderObj.set_brokers(SUPPORTED_BROKERS)
                elif brokers == "day1":
                    orderObj.set_brokers(DAY1_BROKERS)
                elif brokers == "most":
                    orderObj.set_brokers(list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS)))
                elif brokers == "fast":
                    orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
                else:
                    orderObj.set_brokers([nicknames(broker) for broker in brokers.split(",")])
                # Set not brokers if provided
                if not_brokers:
                    for broker in not_brokers.split(","):
                        if nicknames(broker) in SUPPORTED_BROKERS:
                            orderObj.set_notbrokers(nicknames(broker))
                # Run Holdings
                event_loop = asyncio.get_event_loop()
                await bot.loop.run_in_executor(
                    None,
                    fun_run,
                    orderObj,
                    ("_init", "_holdings"),
                    bot,
                    event_loop
                )
                await interaction.followup.send("Holdings complete", ephemeral=interaction.guild is not None)
            except Exception as err:
                print(traceback.format_exc())
                print(f"Error getting holdings: {err}")
                await interaction.followup.send(f"Error getting holdings: {err}", ephemeral=interaction.guild is not None)

        # New transaction command
        @bot.tree.command(name="transaction", description="Execute a transaction (buy/sell)")
        @user_install
        async def transaction(
            interaction: discord.Interaction,
            action: str,
            quantity: str,
            ticker: str,
            accounts: str,
            dry: bool = True
        ):
            try:
                await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
                await interaction.followup.send("Updates on your transactions will be DMed to you!", ephemeral=interaction.guild is not None)
                orderObj = stockOrder()
                # Set the transaction details
                orderObj.set_action(action)
                orderObj.set_amount(quantity)
                # Set stocks
                for stock in ticker.split(","):
                    orderObj.set_stock(stock)
                # Set brokers
                if accounts == "all":
                    orderObj.set_brokers(SUPPORTED_BROKERS)
                elif accounts == "day1":
                    orderObj.set_brokers(DAY1_BROKERS)
                elif accounts == "most":
                    orderObj.set_brokers(list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS)))
                elif accounts == "fast":
                    orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
                else:
                    orderObj.set_brokers([nicknames(broker) for broker in accounts.split(",")])
                # Set dry run option
                orderObj.set_dry(dry)
                # Validate order object
                orderObj.order_validate(preLogin=True)
                # Run Transaction
                event_loop = asyncio.get_event_loop()
                await bot.loop.run_in_executor(
                    None,
                    fun_run,
                    orderObj,
                    ("_init", "_transaction"),
                    bot,
                    event_loop
                )
                await interaction.followup.send("Transaction complete", ephemeral=interaction.guild is not None)
            except Exception as err:
                print(traceback.format_exc())
                print(f"Error placing transaction: {err}")
                await interaction.followup.send(f"Error placing transaction: {err}", ephemeral=interaction.guild is not None)

        # Restart command
        @bot.tree.command(name="restart", description="Restart the bot process")
        @user_install
        async def restart(interaction: discord.Interaction):
            await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
            print("Restarting...")
            print()
            await interaction.followup.send("Restarting...", ephemeral=interaction.guild is not None)
            await bot.close()
            if DOCKER_MODE:
                os._exit(0)  # Special exit code to restart docker container
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)

        @bot.event
        async def on_application_command_error(interaction: discord.Interaction, error: Exception):
            await interaction.response.defer(thinking=True, ephemeral=interaction.guild is not None)
            print(f"An error occurred: {error}")
            await interaction.followup.send_message(f"An error occurred: {str(error)}", ephemeral=interaction.guild is not None)

        # Run Discord bot
        bot.run(DISCORD_TOKEN)
        print("Discord bot is running...")
        print()
