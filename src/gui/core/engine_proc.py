"""Engine subprocess entrypoint.

The GUI runs the trading engine here, in its own child process, so it
executes on a clean main thread with real stdout/stderr — the same
environment the CLI uses. Browser-automation brokers (Fidelity's
Playwright sync API, Chase's zendriver event loop, Selenium) are hostile
to running inside an in-process daemon thread under Streamlit, so they
must not be run that way.

Protocol with the parent:
* stdout/stderr stream straight to the parent (line-buffered, ``-u``).
* When a broker calls ``input()`` (2FA / OTP / CAPTCHA), we emit a
  single sentinel-prefixed line with the prompt text, then block reading
  one line from stdin for the answer.

Invoked as:  python -u -m src.gui.core.engine_proc '<json-encoded args>'
"""

from __future__ import annotations

import builtins
import contextlib
import json
import os
import sys

# Sentinels that cannot occur in normal broker output (NULs around a tag).
PROMPT_SENTINEL = "\x00RSA_PROMPT\x00"
# Account discovery: one line per sub-account seen after login, parsed and
# persisted by the parent (the engine subprocess can't touch the vault).
# Format: ``<ACCOUNT_SENTINEL><broker_key>\t<parent>\t<account>\n``
# (3 tab-separated fields — the parent login is kept so the GUI can
# group discovered sub-accounts by login).
ACCOUNT_SENTINEL = "\x00RSA_ACCT\x00"
# Per-broker run progress for the GUI status bar. One line each:
#   <PROGRESS_SENTINEL>PLAN\t<b1,b2,...>   (once, the planned order)
#   <PROGRESS_SENTINEL>START\t<broker>
#   <PROGRESS_SENTINEL>DONE\t<broker>   or   FAIL\t<broker>
PROGRESS_SENTINEL = "\x00RSA_PROG\x00"


def _bridged_input(prompt: object = "") -> str:
    """Forward an interactive prompt to the parent and read the answer."""
    sys.stdout.write(f"{PROMPT_SENTINEL}{prompt}\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    return line.rstrip("\r\n")


def _reap_leftover_browsers() -> None:
    """Kill any browser subprocesses still alive after the run finishes.

    Browser brokers (Fidelity/Playwright, Chase/zendriver, SoFi/nodriver)
    spawn browser processes that inherit this engine's stdout pipe. Each
    broker closes its own browser inside ``fun_run``; but if a close
    hangs or an error skips it, that browser keeps the pipe's write end
    open after this engine exits. The parent's reader then never sees
    EOF, ``proc.wait()`` is never reached, and the GUI status wedges on
    RUNNING forever — disabling every Execute/Confirm button and making
    a completed purchase look like it never finished.

    ``fun_run`` has already returned by the time this runs, so every
    broker is done and any surviving browser is a leak. Reaping them
    here — from their real parent, before we exit and they get
    re-parented beyond the GUI's reach — closes those pipe fds so the
    parent finalizes cleanly, and stops a zombie browser from locking a
    profile dir on the next run. Best-effort; never raises.
    """
    with contextlib.suppress(Exception):
        sys.stdout.flush()
    try:
        import psutil  # noqa: PLC0415
    except Exception:
        return
    with contextlib.suppress(Exception):
        for child in psutil.Process().children(recursive=True):
            with contextlib.suppress(Exception):
                child.kill()


def main() -> None:
    """Parse args from argv and run the engine, like the CLI does.

    The payload is either a bare args list (holdings / legacy) or a dict
    ``{"args": [...], "price": "market"|"limit", "time": "day"|"gtc"}``.
    arg_parser never sets price/time, so we apply the order-type and
    time-in-force overrides after it builds the order. Brokers that read
    get_price()/get_time() honor them; the rest keep their own automatic
    market->limit / sub-$1 fallback unchanged.
    """
    builtins.input = _bridged_input  # type: ignore[assignment]
    # Marks this as the GUI engine so helper_api emits account-discovery
    # sentinels (kept out of CLI/Docker output).
    os.environ["RSA_GUI_ENGINE"] = "1"
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
    if isinstance(payload, dict):
        args: list[str] = payload.get("args", [])
        price = payload.get("price")
        time_in_force = payload.get("time")
        limit_price = payload.get("limit_price")
    else:
        args = payload
        price = time_in_force = limit_price = None
    # Imported here so the engine's startup banner streams to the parent.
    from src.auto_rsa import arg_parser, fun_run  # noqa: PLC0415

    order = arg_parser(args)
    if price == "limit" and isinstance(limit_price, (int, float)):
        # Explicit price -> StockOrder carries the float; brokers that
        # honor it place a real limit order at exactly this price.
        order.set_price(float(limit_price))
    elif price in {"market", "limit"}:
        # "limit" with no price -> sentinel; brokers fall back to their
        # own native limit logic (sub-$1 / extended-hours auto-price).
        order.set_price(price)
    if time_in_force in {"day", "gtc"}:
        order.set_time(time_in_force)
    try:
        fun_run(order)
    finally:
        # Reap any browser a broker failed to close, so a leaked child
        # can't hold the stdout pipe open and wedge the GUI on RUNNING.
        _reap_leftover_browsers()


if __name__ == "__main__":
    main()
