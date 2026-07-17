# Nelson Dane
# Script to automate RSA stock purchases


# Import libraries
import asyncio
import os
import sys
import traceback
import warnings
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.helper_api import is_up_to_date

if TYPE_CHECKING:
    from src.helper_api import Brokerage

# Filter out old playwright warning: temporary
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="SyntaxWarning: 'continue' in a 'finally' block",
    category=SyntaxWarning,
)

# Alias the vendored robin_stocks so a bare `import robin_stocks` (which the
# vendored library does internally) resolves to the inner package.
# IMPORTANT: import the COMPILED package, not a file-path load — the
# previous spec_from_file_location(vendors/.../__init__.py) needed the .py to
# exist on disk, which it does NOT in a Nuitka one-click build (the submodule
# is compiled into the binary, not shipped as source), so the engine died at
# import on every run. robinhood_api already imports this same package.
try:
    import src.vendors.robin_stocks.robin_stocks as _robin_stocks

    sys.modules.setdefault("robin_stocks", _robin_stocks)
    robin_stocks = _robin_stocks
except ImportError:
    # Vendored submodule absent (a dev checkout without submodules). Not
    # fatal here: robinhood_api imports it directly and fails loudly there
    # if Robinhood is actually used; every other broker is unaffected.
    pass

# Print Startup Info
print(f"Python version: {sys.version}")
print(f"Platform: {sys.platform}")
print(f"Current Directory: {Path.cwd()}")
try:
    CURRENT_RSA_VERSION = version("auto_rsa_bot")
except Exception:  # noqa: BLE001 -- PackageNotFoundError in a frozen build; degrade
    CURRENT_RSA_VERSION = "0.0.0"
# Check to see if directory contains .env file
print(f"Directory Contains .env File: {Path('.env').exists()}")
print(f"RSA Version: {CURRENT_RSA_VERSION}")
print()

try:
    import discord as discord_module
    from discord.ext import commands
    from dotenv import load_dotenv

    # Custom API libraries (These are inferred from the namespace in fun_run, so the import is needed)
    from src.brokerages.bbae_api import bbae_holdings, bbae_init, bbae_transaction
    from src.brokerages.chase_api import chase_run
    from src.brokerages.dspac_api import dspac_holdings, dspac_init, dspac_transaction
    from src.brokerages.fennel_api import fennel_holdings, fennel_init, fennel_transaction
    from src.brokerages.fidelity_api import fidelity_run
    from src.brokerages.firstrade_api import firstrade_holdings, firstrade_init, firstrade_transaction
    from src.brokerages.public_api import public_holdings, public_init, public_transaction
    from src.brokerages.robinhood_api import robinhood_holdings, robinhood_init, robinhood_transaction
    from src.brokerages.schwab_api import schwab_holdings, schwab_init, schwab_transaction
    from src.brokerages.sofi_api import sofi_run
    from src.brokerages.tasty_api import tastytrade_holdings, tastytrade_init, tastytrade_transaction
    from src.brokerages.tornado_api import tornado_holdings, tornado_init, tornado_transaction
    from src.brokerages.tradier_api import tradier_holdings, tradier_init, tradier_transaction
    from src.brokerages.vanguard_api import vanguard_run
    from src.brokerages.webull_api import webull_holdings, webull_init, webull_transaction
    from src.brokerages.wellsfargo_api import wellsfargo_holdings, wellsfargo_init, wellsfargo_transaction
    from src.brokers import AllBrokersInfo, BrokerName
    from src.helper_api import StockOrder, ThreadHandler, print_and_discord
except Exception as e:
    print(f"Error importing libraries: {e}")
    print(traceback.format_exc())
    sys.exit(1)

# Initialize .env file
load_dotenv()
DANGER_MODE = os.getenv("DANGER_MODE", "").lower() == "true"

# Per-broker watchdog: max seconds a single ThreadHandler broker
# (Chase/Fidelity/Vanguard/SoFi browser flows) may run before it's
# abandoned so the run/scheduler can't hang forever. Generous by
# default (multi-account holdings + 2FA approve take minutes);
# override with RSA_BROKER_TIMEOUT.
_DEFAULT_BROKER_TIMEOUT = 600


def _broker_timeout() -> int:
    try:
        return max(60, int(os.getenv("RSA_BROKER_TIMEOUT", str(_DEFAULT_BROKER_TIMEOUT))))
    except ValueError:
        return _DEFAULT_BROKER_TIMEOUT


def _emit_progress(kind: str, value: str) -> None:
    """Emit a run-progress sentinel for the GUI status bar.

    Only inside the GUI engine subprocess (RSA_GUI_ENGINE=1); a no-op
    for the CLI so its output stays clean. Best-effort.
    """
    if os.getenv("RSA_GUI_ENGINE") != "1":
        return
    try:
        from src.gui.core.engine_proc import PROGRESS_SENTINEL  # noqa: PLC0415

        # Single write incl. the newline (not print(), which writes the
        # text and "\n" separately) so a concurrent broker thread in a
        # parallel run can't interleave and split this sentinel line —
        # the short line stays atomic on the pipe (< PIPE_BUF). No-op
        # difference for the single-threaded sequential path.
        sys.stdout.write(f"{PROGRESS_SENTINEL}{kind}\t{value}\n")
        sys.stdout.flush()
    except Exception as exc:  # progress is best-effort
        print(f"(progress emit skipped: {exc})")


def _order_run_blocked(order_obj: StockOrder) -> tuple[bool, str]:
    """Whether a real order run is forbidden (kill switch / revoke / license).

    Only a REAL order run is gated: read-only holdings runs and dry runs
    are never blocked. Delegates to ``client.pre_trade_block``, which
    catches the kill switch (423), a revoked/expired license (410), and —
    in a Friend build (``REQUIRE_LICENSE_TO_TRADE``) — an install that
    never activated. Fails OPEN on any error so a network blip or an
    unconfigured server never freezes a legitimate run; revoke is the hard
    backstop. Independent of the license-cap bypass on purpose: a
    safety/kill stop applies even to a bypassed operator.
    """
    try:
        if order_obj.get_holdings() or order_obj.get_dry():
            return False, ""
        from src.license import _keys  # noqa: PLC0415
        from src.license.client import pre_trade_block  # noqa: PLC0415

        from src.helper_api import broker_cap_message  # noqa: PLC0415

        require = bool(getattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False))
        blocked, msg = pre_trade_block(require_license=require)
        if blocked:
            return True, msg
        cap_msg = broker_cap_message(order_obj)
        if cap_msg:
            return True, cap_msg
        return False, ""
    except Exception:
        return False, ""


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
    # Kill-switch preflight: refuse a real order run when the operator has
    # flipped the remote stop (crucial-bug halt). Plain ASCII so it prints
    # safely on any console encoding (no emoji).
    blocked, kill_msg = _order_run_blocked(order_obj)
    if blocked:
        print("=" * 60)
        print("ORDER PLACEMENT BLOCKED — no orders were placed.")
        # kill_msg carries the specific reason (kill switch, revoked/expired
        # license, or no license activated) — don't hardcode "kill switch".
        print(kill_msg or "Blocked by the operator.")
        print("=" * 60)
        _emit_progress("KILL", kill_msg or "blocked")
        return
    # Reset the per-broker sub-account counters at the start of each run so
    # a Friend tier's "1 account per broker" cap is measured per run, not
    # across the life of a long-lived process (Discord bot / scheduler).
    from src.helper_api import reset_subaccount_caps  # noqa: PLC0415

    reset_subaccount_caps()
    total_value = 0
    planned = [
        bi.name.lower()
        for bi in order_obj.get_brokers()
        if bi not in order_obj.get_notbrokers()
    ]
    _emit_progress("PLAN", ",".join(planned))
    # Plain-text plan so the GUI/console log shows exactly which brokers
    # this run will touch. Without it, a run that (for any reason) resolved
    # to fewer brokers than the operator selected looks like a silent
    # no-op: they see one broker work and can't tell the others were never
    # in the list vs. ran-and-failed. This line makes the scope explicit.
    if planned:
        print(f"Running {len(planned)} broker(s): {', '.join(planned)}")
    else:
        print("No brokers to run — the resolved broker list is empty.")
    for broker_info in order_obj.get_brokers():
        if broker_info in order_obj.get_notbrokers():
            continue
        broker = broker_info.name.lower()
        broker_failed = False
        _emit_progress("START", broker)
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
                # Start single run thread, bounded by a watchdog so a
                # wedged broker (e.g. a browser market order stuck after
                # hours, or a flaky nodriver session) can never freeze
                # the whole run / unattended scheduler. On timeout the
                # daemon thread is abandoned and the next broker runs.
                th.start()
                th.join(timeout=_broker_timeout())
                if th.is_alive():
                    msg = (
                        f"Error in {broker}: timed out after "
                        f"{_broker_timeout()}s (broker stuck — abandoned; "
                        f"other brokers continue)"
                    )
                    raise Exception(msg)
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
                # Track per-broker total so we can show accurate totals and still accumulate overall
                broker_total = sum(account["total"] for account in order_obj.get_logged_in(broker).get_account_totals().values())
                print_and_discord(f"Total Value of {broker.title()} Accounts: ${format(broker_total, '0.2f')}", loop)
                # Add to overall total sum
                total_value += broker_total
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
            broker_failed = True
        finally:
            # Runs on every path (success, the ThreadHandler `continue`,
            # or an exception) so the GUI status bar is always accurate.
            _emit_progress("FAIL" if broker_failed else "DONE", broker)
            print()

    # Print final total value and closing message once after all brokers
    if order_obj.get_holdings():
        print_and_discord(f"Combined Total Value Across Brokers: ${format(total_value, '0.2f')}", loop)
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
            else:
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
