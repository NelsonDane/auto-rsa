# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import asyncio
import os
import sys
import traceback
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from src.helper_api import is_up_to_date

if TYPE_CHECKING:
    from src.helper_api import Brokerage

# Print Startup Info
print(f"Python version: {sys.version}")
print(f"Platform: {sys.platform}")
CURRENT_RSA_VERSION = version("auto_rsa_bot")
print(f"RSA Version: {CURRENT_RSA_VERSION}")
print()

try:
    import discord as discord_module
    from discord.ext import commands
    from dotenv import load_dotenv

    # Custom API libraries (These are inferred from the namespace in fun_run, so the import is needed)
    from .brokerages.bbae_api import bbae_holdings, bbae_init, bbae_transaction
    from .brokerages.chase_api import chase_run
    from .brokerages.dspac_api import dspac_holdings, dspac_init, dspac_transaction
    from .brokerages.fennel_api import fennel_holdings, fennel_init, fennel_transaction
    from .brokerages.fidelity_api import fidelity_run
    from .brokerages.firstrade_api import firstrade_holdings, firstrade_init, firstrade_transaction
    from .brokerages.public_api import public_holdings, public_init, public_transaction
    from .brokerages.robinhood_api import robinhood_holdings, robinhood_init, robinhood_transaction
    from .brokerages.schwab_api import schwab_holdings, schwab_init, schwab_transaction
    from .brokerages.sofi_api import sofi_run
    from .brokerages.tasty_api import tastytrade_holdings, tastytrade_init, tastytrade_transaction
    from .brokerages.tornado_api import tornado_holdings, tornado_init, tornado_transaction
    from .brokerages.tradier_api import tradier_holdings, tradier_init, tradier_transaction
    from .brokerages.vanguard_api import vanguard_run
    from .brokerages.webull_api import webull_holdings, webull_init, webull_transaction
    from .brokerages.wellsfargo_api import wellsfargo_holdings, wellsfargo_init, wellsfargo_transaction
    from .brokers import AllBrokersInfo, BrokerName
    from .helper_api import StockOrder, ThreadHandler, print_and_discord
except Exception as e:
    print(f"Error importing libraries: {e}")
    print(traceback.format_exc())
    sys.exit(1)

# Initialize .env file
load_dotenv()
DANGER_MODE = os.getenv("DANGER_MODE", "").lower() == "true"


def fun_run(  # noqa: C901, PLR0912, PLR0915
    order_obj: StockOrder,
    bot_obj: commands.Bot | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    *,
    docker_mode: bool = False,
) -> None:
    """Run the specified function for each broker in the list.

    Functions are determined as: [broker_name] + <function_name>.
    So for example, fennel init -> fennel_init()
    """
    total_value = 0
    for broker_info in order_obj.get_brokers():
        if broker_info in order_obj.get_notbrokers():
            continue
        broker = broker_info.name.lower()
        try:
            success: Brokerage | None = None
            th: ThreadHandler | None = None
            # Initialize broker
            match broker_info.name:
                case BrokerName.BBAE:
                    success = bbae_init(bot_obj=bot_obj, loop=loop)
                case BrokerName.CHASE:
                    th = ThreadHandler(
                        chase_run,
                        order_obj=order_obj,
                        bot_obj=bot_obj,
                        loop=loop,
                    )
                case BrokerName.DSPAC:
                    success = dspac_init(bot_obj=bot_obj, loop=loop)
                case BrokerName.FENNEL:
                    success = fennel_init(loop=loop)
                case BrokerName.FIDELITY:
                    th = ThreadHandler(
                        fidelity_run,
                        order_obj=order_obj,
                        bot_obj=bot_obj,
                        loop=loop,
                    )
                case BrokerName.FIRSTRADE:
                    success = firstrade_init(bot_obj=bot_obj, loop=loop)
                case BrokerName.PUBLIC:
                    success = public_init(loop=loop)
                case BrokerName.ROBINHOOD:
                    success = robinhood_init(loop=loop)
                case BrokerName.SCHWAB:
                    success = schwab_init()
                case BrokerName.SOFI:
                    th = ThreadHandler(
                        sofi_run,
                        order_obj=order_obj,
                        bot_obj=bot_obj,
                        loop=loop,
                    )
                case BrokerName.TASTYTRADE:
                    success = tastytrade_init()
                case BrokerName.TORNADO:
                    success = tornado_init(docker_mode=docker_mode, loop=loop)
                case BrokerName.TRADIER:
                    success = tradier_init()
                case BrokerName.VANGUARD:
                    th = ThreadHandler(
                        vanguard_run,
                        order_obj=order_obj,
                        bot_obj=bot_obj,
                        loop=loop,
                    )
                case BrokerName.WEBULL:
                    success = webull_init()
                case BrokerName.WELLS_FARGO:
                    success = wellsfargo_init(
                        bot_obj=bot_obj,
                        docker_mode=docker_mode,
                        loop=loop,
                    )
            if th is not None:
                # Start single run thread
                th.start()
                th.join()
                _, err = th.get_result()
                if err is not None:
                    msg = f"Error in {broker}: Function did not complete successfully: {err}"
                    raise Exception(msg)
                continue
            if success is None:
                msg = f"Error in {broker}: Function did not complete successfully"
                raise Exception(msg)
            # Success
            order_obj.set_logged_in(success, broker)
            print()
            # Verify broker is logged in
            order_obj.order_validate(pre_login=False)
            logged_in_broker = order_obj.get_logged_in(broker)
            if logged_in_broker is None:
                print(f"Error: {broker} not logged in, skipping...")
                continue
            if order_obj.get_holdings():
                match broker_info.name:
                    case BrokerName.BBAE:
                        bbae_holdings(logged_in_broker, loop)
                    case BrokerName.DSPAC:
                        dspac_holdings(logged_in_broker, loop)
                    case BrokerName.FENNEL:
                        fennel_holdings(logged_in_broker, loop)
                    case BrokerName.FIRSTRADE:
                        firstrade_holdings(logged_in_broker, loop)
                    case BrokerName.PUBLIC:
                        public_holdings(logged_in_broker, loop)
                    case BrokerName.ROBINHOOD:
                        robinhood_holdings(logged_in_broker, loop)
                    case BrokerName.SCHWAB:
                        schwab_holdings(logged_in_broker, loop)
                    case BrokerName.TASTYTRADE:
                        tastytrade_holdings(logged_in_broker, loop)
                    case BrokerName.TORNADO:
                        tornado_holdings(logged_in_broker, loop)
                    case BrokerName.TRADIER:
                        tradier_holdings(logged_in_broker, loop)
                    case BrokerName.WEBULL:
                        webull_holdings(logged_in_broker, loop)
                    case BrokerName.WELLS_FARGO:
                        wellsfargo_holdings(logged_in_broker, loop)
                # Add to total sum
                total_value += sum(account["total"] for account in order_obj.get_logged_in(broker).get_account_totals().values())
            else:
                # Run transaction
                match broker_info.name:
                    case BrokerName.BBAE:
                        bbae_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.DSPAC:
                        dspac_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.FENNEL:
                        fennel_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.FIRSTRADE:
                        firstrade_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.PUBLIC:
                        public_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.ROBINHOOD:
                        robinhood_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.SCHWAB:
                        schwab_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.TASTYTRADE:
                        tastytrade_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.TORNADO:
                        tornado_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.TRADIER:
                        tradier_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.WEBULL:
                        webull_transaction(logged_in_broker, order_obj, loop)
                    case BrokerName.WELLS_FARGO:
                        wellsfargo_transaction(logged_in_broker, order_obj, loop)
                print_and_discord(
                    f"All {broker.capitalize()} transactions complete",
                    loop,
                )
        except Exception as ex:
            print(traceback.format_exc())
            print(f"Error with {broker}: {ex}")
            print(order_obj)
        print()

        # Print final total value and closing message
        if order_obj.get_holdings():
            print_and_discord(
                f"Total Value of All Accounts: ${format(total_value, '0.2f')}",
                loop,
            )
        print_and_discord("All commands complete in all brokers", loop)


def arg_parser(args: list[str]) -> StockOrder:  # noqa: C901, PLR0912
    """Parse input arguments to create a StockOrder object."""
    args = [x.lower() for x in args]
    # Initialize objects
    stock_order = StockOrder()
    all_brokers = AllBrokersInfo()
    # If first argument is holdings, set holdings to true
    if args[0] == "holdings":
        stock_order.set_holdings(holdings=True)
        # Next argument is brokers
        if args[1] == "all":
            stock_order.set_brokers(all_brokers.get_all())
        elif args[1] == "day1":
            stock_order.set_brokers(all_brokers.get_day_one())
        elif args[1] == "most":
            stock_order.set_brokers(all_brokers.get_most())
        elif args[1] == "fast":
            stock_order.set_brokers(all_brokers.get_fast())
        else:
            for broker in args[1].split(","):
                broker_enum = all_brokers.parse_input(broker)
                if broker_enum:
                    stock_order.set_brokers(broker_enum)
        # If next argument is not, set not broker
        if len(args) > 3 and args[2] == "not":  # noqa: PLR2004
            for broker in args[3].split(","):
                broker_enum = all_brokers.parse_input(broker)
                if broker_enum:
                    stock_order.set_notbrokers(broker_enum)
        return stock_order
    # Otherwise: action, amount, stock, broker, (optional) not broker, (optional) dry
    if args[0] == "buy":
        stock_order.set_action("buy")
    elif args[0] == "sell":
        stock_order.set_action("sell")
    stock_order.set_amount(float(args[1]))
    for stock in args[2].split(","):
        if stock:
            stock_order.set_stock(stock)
    # Next argument is a broker, set broker
    if args[3] == "all":
        stock_order.set_brokers(all_brokers.get_all())
    elif args[3] == "day1":
        stock_order.set_brokers(all_brokers.get_day_one())
    elif args[3] == "most":
        stock_order.set_brokers(all_brokers.get_most())
    elif args[3] == "fast":
        stock_order.set_brokers(all_brokers.get_fast())
    else:
        for broker in args[3].split(","):
            broker_enum = all_brokers.parse_input(broker)
            if broker_enum:
                stock_order.set_brokers(broker_enum)
    # If next argument is not, set not broker
    if len(args) > 4 and args[4] == "not":  # noqa: PLR2004
        for broker in args[5].split(","):
            broker_enum = all_brokers.parse_input(broker)
            if broker_enum:
                stock_order.set_notbrokers(broker_enum)
    # If next argument is false, set dry to false
    if args[-1] == "false":
        stock_order.set_dry(dry=False)
    # Validate order object
    stock_order.order_validate(pre_login=True)
    return stock_order


def main(args: list[str]) -> None:  # noqa: C901, PLR0912, PLR0915
    """Entrypoint for the CLI."""
    # Determine if ran from command line
    docker_mode = discord_bot = False
    print("Running main with args:", args)
    if len(args) == 0:  # If no arguments, do nothing
        print("No arguments given, see README for usage")
        sys.exit(1)
    # Check if danger mode is enabled
    if DANGER_MODE:
        print("DANGER MODE ENABLED")
        print()
    # If docker argument, run docker bot
    if args[0].lower() == "docker":
        print("Running bot from docker")
        docker_mode = discord_bot = True
    # If discord argument, run discord bot, no docker, no prompt
    elif args[0].lower() == "discord":
        print("Running Discord bot from command line")
        is_up_to_date()
        discord_bot = True
    else:  # If any other argument, run bot, no docker or discord bot
        print("Running bot from command line")
        is_up_to_date()
        print()
        cli_order_obj = arg_parser(args)
        if not cli_order_obj.get_holdings():
            print(f"Action: {cli_order_obj.get_action()}")
            print(f"Amount: {cli_order_obj.get_amount()}")
            print(f"Stock: {cli_order_obj.get_stocks()}")
            print(f"Time: {cli_order_obj.get_time()}")
            print(f"Price: {cli_order_obj.get_price()}")
            print(f"Broker: {cli_order_obj.get_brokers()}")
            print(f"Not Broker: {cli_order_obj.get_notbrokers()}")
            print(f"DRY: {cli_order_obj.get_dry()}")
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
        cli_order_obj.order_validate(pre_login=True)
        # Get holdings or complete transaction
        if cli_order_obj.get_holdings():
            fun_run(cli_order_obj, docker_mode=docker_mode)
        else:
            fun_run(cli_order_obj, docker_mode=docker_mode)
        sys.exit(0)

    # If discord bot, run discord bot
    if discord_bot:
        # Get discord token and channel from .env file
        discord_token = os.getenv("DISCORD_TOKEN")
        if not discord_token:
            msg = "DISCORD_TOKEN not found in .env file, please add it"
            raise Exception(msg)
        channel_test = os.getenv("DISCORD_CHANNEL")
        if not channel_test:
            msg = "DISCORD_CHANNEL not found in .env file, please add it"
            raise Exception(msg)
        discord_channel = int(channel_test)
        custom_prefix = os.getenv("DISCORD_PREFIX", "!")
        custom_rsa_command = os.getenv("DISCORD_RSA_COMMAND", "rsa")
        # Initialize discord bot
        intents = discord_module.Intents.default()
        intents.message_content = True
        # Discord bot command prefix
        bot = commands.Bot(command_prefix=custom_prefix, intents=intents)
        bot.remove_command("help")
        print()
        print("Discord bot is started...")
        print()

        @bot.event
        async def on_ready() -> None:
            """Bot event run when bot is started."""
            channel = bot.get_channel(discord_channel)
            if not isinstance(channel, discord_module.TextChannel):
                print(
                    "ERROR: Invalid channel ID, please check your DISCORD_CHANNEL in your .env file and try again",
                )
                os._exit(1)  # Special exit code to restart docker container
            await channel.send("Discord bot is started...")

        @bot.event
        async def on_message(message: discord_module.Message) -> None:
            """Process the message only if it's from the allowed channel."""
            if message.channel.id == discord_channel and message.author != bot.user:
                ctx = await bot.get_context(message)
                await bot.invoke(ctx)

        @bot.command(name="ping")
        async def ping(ctx: commands.Context[Any]) -> None:
            """Ping-pong test command."""
            print("ponged")
            await ctx.send("pong")

        @bot.command()
        async def help(ctx: commands.Context[Any]) -> None:  # noqa: A001
            """Return a list of available commands."""
            await ctx.send(
                "Available RSA commands:\n!ping\n!help\n!rsa holdings [all|<broker1>,<broker2>,...] [not broker1,broker2,...]\n!rsa [buy|sell] [amount] [stock1|stock1,stock2] [all|<broker1>,<broker2>,...] [not broker1,broker2,...] [DRY: true|false]\n!restart",
            )

        @bot.command(name="version")
        async def version(ctx: commands.Context[Any]) -> None:
            """Print the version of the application."""
            await ctx.send(f"RSA Version: {CURRENT_RSA_VERSION}")

        @bot.command(name=custom_rsa_command)
        async def rsa(ctx: commands.Context[Any], *args: tuple[str]) -> None:
            """Run init/holdings/transaction in Discord."""
            parsed_args = ["".join(t) for t in args]
            print(f"Received RSA command with args: {parsed_args}")
            discord_order_obj = await bot.loop.run_in_executor(None, arg_parser, parsed_args)
            event_loop = asyncio.get_event_loop()
            try:
                # Validate order object
                discord_order_obj.order_validate(pre_login=True)
                # Get holdings or complete transaction
                if discord_order_obj.get_holdings():
                    # Run Holdings
                    await bot.loop.run_in_executor(
                        None,
                        lambda: fun_run(
                            discord_order_obj,
                            bot,
                            event_loop,
                            docker_mode=docker_mode,
                        ),
                    )
                else:
                    # Run Transaction
                    await bot.loop.run_in_executor(
                        None,
                        lambda: fun_run(
                            discord_order_obj,
                            bot,
                            event_loop,
                            docker_mode=docker_mode,
                        ),
                    )
            except Exception as err:
                print(traceback.format_exc())
                print(f"Error placing order: {err}")
                if ctx:
                    await ctx.send(f"Error placing order: {err}")

        @bot.command(name="restart")
        async def restart(ctx: commands.Context[Any]) -> None:
            """Restart the bot."""
            print("Restarting...")
            print()
            await ctx.send("Restarting...")
            await bot.close()
            if docker_mode:
                os._exit(0)  # Special exit code to restart docker container
            else:
                os.execv(sys.executable, [sys.executable, *sys.argv])  # noqa: S606

        @bot.event
        async def on_command_error(
            ctx: commands.Context[Any],
            error: Exception,
        ) -> None:
            """Handle command errors."""
            print(f"Command Error: {error}")
            await ctx.send(f"Command Error: {error}")
            # Print help command
            print("Type '!help' for a list of commands")
            await ctx.send("Type '!help' for a list of commands")

        # Run Discord bot
        bot.run(discord_token)
        print("Discord bot is running...")
        print()
