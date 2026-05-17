"""Runs holdings/trade operations against the existing AutoRSA engine.

The GUI never reimplements broker logic. It builds the same argument list
the CLI uses, then calls ``arg_parser`` + ``fun_run`` from
``src.auto_rsa`` on a background thread with:

* stdout/stderr redirected into a :class:`LogStream`
* ``builtins.input`` redirected to a :class:`PromptBus` (so 2FA/OTP/CAPTCHA
  prompts surface in the browser instead of blocking on a dead stdin)
* credentials materialized into ``os.environ`` only for the run's duration
"""

from __future__ import annotations

import builtins
import contextlib
import threading
import traceback
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from src.gui.core.logbus import LogStream
from src.gui.core.prompts import PromptBus

if TYPE_CHECKING:
    from src.gui.core.vault import Vault


class RunStatus(StrEnum):
    """Lifecycle of a single GUI-triggered operation."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RunnerSnapshot:
    """Immutable view of runner state for the UI."""

    status: RunStatus
    description: str
    log: str


class TradeRunner:
    """Owns the worker thread, log stream, and prompt bus for one session."""

    def __init__(self, vault: Vault) -> None:
        """Bind the runner to a vault; no work starts until a run is requested."""
        self._vault = vault
        self.log = LogStream()
        self.prompts = PromptBus()
        self._thread: threading.Thread | None = None
        self._status = RunStatus.IDLE
        self._description = ""
        self._lock = threading.Lock()

    # --- state ---------------------------------------------------------

    def is_running(self) -> bool:
        """Whether a worker thread is currently active."""
        with self._lock:
            return self._status == RunStatus.RUNNING

    def snapshot(self) -> RunnerSnapshot:
        """Non-blocking view of status + captured log."""
        with self._lock:
            return RunnerSnapshot(self._status, self._description, self.log.getvalue())

    # --- public operations --------------------------------------------

    def start_holdings(self, broker_keys: list[str]) -> None:
        """Pull balances/holdings for the given brokers (or ['all'])."""
        args = ["holdings", self._brokers_arg(broker_keys)]
        self._start(args, broker_keys, f"Holdings: {', '.join(broker_keys)}")

    def start_trade(
        self,
        action: str,
        amount: float,
        tickers: list[str],
        broker_keys: list[str],
        *,
        dry: bool,
    ) -> None:
        """Execute a buy/sell. ``dry=True`` performs a no-op dry run."""
        args = [
            action,
            str(amount),
            ",".join(t.strip() for t in tickers if t.strip()),
            self._brokers_arg(broker_keys),
            "true" if dry else "false",
        ]
        mode = "DRY" if dry else "LIVE"
        desc = (
            f"{mode} {action} {amount} {','.join(tickers)} "
            f"-> {', '.join(broker_keys)}"
        )
        self._start(args, broker_keys, desc)

    # --- internals -----------------------------------------------------

    @staticmethod
    def _brokers_arg(broker_keys: list[str]) -> str:
        if "all" in broker_keys:
            return "all"
        return ",".join(broker_keys)

    def _resolve_broker_keys(self, broker_keys: list[str]) -> list[str]:
        if "all" in broker_keys:
            return self._vault.configured_broker_keys()
        return broker_keys

    def _start(self, args: list[str], broker_keys: list[str], description: str) -> None:
        with self._lock:
            if self._status == RunStatus.RUNNING:
                msg = "A run is already in progress."
                raise RuntimeError(msg)
            self._status = RunStatus.RUNNING
            self._description = description
        self.log.clear()
        env_keys = self._resolve_broker_keys(broker_keys)
        self._thread = threading.Thread(
            target=self._worker,
            args=(args, env_keys),
            daemon=True,
        )
        self._thread.start()

    def _patched_input(self, prompt: object = "") -> str:
        return self.prompts.request(str(prompt))

    def _worker(self, args: list[str], env_keys: list[str]) -> None:
        real_input = builtins.input
        builtins.input = self._patched_input  # type: ignore[assignment]
        try:
            with (
                contextlib.redirect_stdout(self.log),
                contextlib.redirect_stderr(self.log),
            ):
                try:
                    # Imported lazily so the heavy broker/selenium imports
                    # (and their startup banner) are captured in the log and
                    # don't slow down credential management.
                    from src.auto_rsa import arg_parser, fun_run  # noqa: PLC0415

                    order = arg_parser(args)
                    with self._vault.materialize_env(env_keys):
                        fun_run(order)
                    self._set_status(RunStatus.FINISHED)
                except Exception:
                    print("\n--- GUI run failed ---")
                    print(traceback.format_exc())
                    self._set_status(RunStatus.ERROR)
        finally:
            builtins.input = real_input
            # Never leave a worker blocked on a prompt nobody will answer.
            self.prompts.cancel()

    def _set_status(self, status: RunStatus) -> None:
        with self._lock:
            self._status = status
