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
import json
import sys

# Sentinel that cannot occur in normal broker output (NULs around a tag).
PROMPT_SENTINEL = "\x00RSA_PROMPT\x00"


def _bridged_input(prompt: object = "") -> str:
    """Forward an interactive prompt to the parent and read the answer."""
    sys.stdout.write(f"{PROMPT_SENTINEL}{prompt}\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    return line.rstrip("\r\n")


def main() -> None:
    """Parse args from argv and run the engine, like the CLI does."""
    builtins.input = _bridged_input  # type: ignore[assignment]
    args: list[str] = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
    # Imported here so the engine's startup banner streams to the parent.
    from src.auto_rsa import arg_parser, fun_run  # noqa: PLC0415

    order = arg_parser(args)
    fun_run(order)


if __name__ == "__main__":
    main()
