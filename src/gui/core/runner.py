"""Runs holdings/trade operations via the existing AutoRSA engine.

The engine runs in a **child process**, not an in-process thread. This
is deliberate: browser-automation brokers (Fidelity's Playwright sync
API, Chase's zendriver event loop, Selenium) fail when run inside a
daemon thread under Streamlit with swapped stdio. A subprocess gives
them a clean main thread and real stdout/stderr — the same environment
the CLI uses, where those brokers work.

The parent only does pipe I/O on a reader thread:
* stdout/stderr stream into a :class:`LogStream`.
* sentinel-prefixed lines are 2FA/OTP/CAPTCHA prompts: they go to the
  :class:`PromptBus`, and the UI's answer is written back to the child's
  stdin.
* credentials are passed via the child's environment (never written to
  disk, never set on the parent's environment).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from src.gui.core.engine_proc import PROMPT_SENTINEL
from src.gui.core.logbus import LogStream
from src.gui.core.prompts import PromptBus

if TYPE_CHECKING:
    from src.gui.core.vault import Vault

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    """Owns the engine subprocess, log stream, and prompt bus."""

    def __init__(self, vault: Vault) -> None:
        """Bind the runner to a vault; no work starts until a run is requested."""
        self._vault = vault
        self.log = LogStream()
        self.prompts = PromptBus()
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._status = RunStatus.IDLE
        self._description = ""
        self._lock = threading.Lock()

    # --- state ---------------------------------------------------------

    def is_running(self) -> bool:
        """Whether the engine subprocess is currently active."""
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

    def start_trade(  # noqa: PLR0913
        self,
        action: str,
        amount: float,
        tickers: list[str],
        broker_keys: list[str],
        *,
        dry: bool,
        price_type: str = "market",
        time_in_force: str = "day",
    ) -> None:
        """Execute a buy/sell.

        ``price_type`` ("market"/"limit") and ``time_in_force``
        ("day"/"gtc") are plumbed onto the StockOrder. Brokers that read
        them honor them; the rest keep their own automatic
        market->limit / sub-$1 fallback. ``dry=True`` is a no-op run.
        """
        args = [
            action,
            str(amount),
            ",".join(t.strip() for t in tickers if t.strip()),
            self._brokers_arg(broker_keys),
            "true" if dry else "false",
        ]
        payload = {"args": args, "price": price_type, "time": time_in_force}
        mode = "DRY" if dry else "LIVE"
        desc = (
            f"{mode} {action} {amount} {','.join(tickers)} "
            f"[{price_type}/{time_in_force}] -> {', '.join(broker_keys)}"
        )
        self._start(payload, broker_keys, desc)

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

    def _start(
        self,
        payload: list[str] | dict[str, object],
        broker_keys: list[str],
        description: str,
    ) -> None:
        with self._lock:
            if self._status == RunStatus.RUNNING:
                msg = "A run is already in progress."
                raise RuntimeError(msg)
            self._status = RunStatus.RUNNING
            self._description = description
        self.log.clear()
        env_keys = self._resolve_broker_keys(broker_keys)
        # Credentials go to the child's environment only.
        child_env = {**os.environ, **self._vault.build_env(env_keys)}
        self._proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", "-m", "src.gui.core.engine_proc", json.dumps(payload)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(_PROJECT_ROOT),
            env=child_env,
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            self._set_status(RunStatus.ERROR)
            return
        try:
            for raw in proc.stdout:
                if raw.startswith(PROMPT_SENTINEL):
                    text = raw[len(PROMPT_SENTINEL):].rstrip("\r\n")
                    self.prompts.open(text)
                    answer = self.prompts.wait_answer()
                    if proc.stdin is not None:
                        proc.stdin.write(answer + "\n")
                        proc.stdin.flush()
                else:
                    self.log.write(raw)
        except Exception as exc:
            self.log.write(f"\n--- GUI pump error: {exc} ---\n")
        finally:
            code = proc.wait()
            self.prompts.cancel()
            self._set_status(RunStatus.FINISHED if code == 0 else RunStatus.ERROR)

    def _set_status(self, status: RunStatus) -> None:
        with self._lock:
            self._status = status
