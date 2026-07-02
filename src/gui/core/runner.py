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

import contextlib
import datetime
import json
import os
import subprocess  # noqa: S404
import sys
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
import requests

from src.gui.core.engine_proc import (
    ACCOUNT_SENTINEL,
    PROGRESS_SENTINEL,
    PROMPT_SENTINEL,
)
from src.gui.core.logbus import LogStream
from src.gui.core.prompts import PromptBus
from src.outcomes import is_fill_line

if TYPE_CHECKING:
    from src.gui.core.vault import Vault

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_LOCK = _PROJECT_ROOT / "creds" / "run.lock"
_STALE_LOCK_SECONDS = 6 * 60 * 60  # a lock with no live engine, this old, is stale
_DISCOVERY_FIELDS = 3  # <SENTINEL>broker\tparent\taccount
# Redaction thresholds. The corruption risk is SHORT, PURELY-NUMERIC
# secrets (a 4-6 digit PIN/code) which collide with digits inside
# balances/totals/timestamps and silently rewrite the real-money audit
# log. So: redact anything >= _REDACT_MIN_LEN, and shorter values only
# when they contain a non-digit (an alphanumeric token is unambiguous);
# never blind-replace a short all-numeric secret.
_REDACT_MIN_LEN = 8
_REDACT_ALNUM_MIN_LEN = 5


class RunBusyError(RuntimeError):
    """Raised when another AutoRSA run already holds the single-instance lock."""


class RunStatus(StrEnum):
    """Lifecycle of a single GUI-triggered operation."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunnerSnapshot:
    """Immutable view of runner state for the UI."""

    status: RunStatus
    description: str
    log: str
    # Ordered per-broker run progress: (broker, "pending"|"running"|
    # "done"|"done_no_fill"|"failed"). "done" = >=1 confirmed fill;
    # "done_no_fill" = broker ran clean but placed no orders (e.g.
    # stock unavailable on every account). Empty for runs that emit
    # no progress.
    progress: tuple[tuple[str, str], ...] = ()


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
        self._cancelled = False
        self._secrets: list[str] = []
        self._progress: dict[str, str] = {}
        self._current_broker: str | None = None
        self._fill_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _redactable(secret: str) -> bool:
        n = len(secret)
        if n >= _REDACT_MIN_LEN:
            return True
        # Short value: only redact if it carries a non-digit (an
        # alphanumeric token won't collide with numbers in the log).
        return n >= _REDACT_ALNUM_MIN_LEN and not secret.isdigit()

    def _redact(self, text: str) -> str:
        # Longest first so a long secret isn't left half-masked by a
        # shorter one that's a substring of it. Short all-numeric secrets
        # are skipped so redaction can't rewrite unrelated numbers in the
        # audit log.
        for secret in sorted(self._secrets, key=len, reverse=True):
            if self._redactable(secret):
                text = text.replace(secret, "***")
        return text

    # --- state ---------------------------------------------------------

    def is_running(self) -> bool:
        """Whether the engine subprocess is currently active.

        Self-heals first: a browser broker can leave a zombie browser
        child that inherited the engine's stdout pipe, so the pump
        reader never sees EOF, ``proc.wait()`` is never reached, and
        the status is wedged on RUNNING forever — disabling every
        Execute/Confirm button. :meth:`_reap_if_stuck` detects the
        engine having actually exited and finalizes the run so the UI
        unblocks.
        """
        self._reap_if_stuck()
        with self._lock:
            return self._status == RunStatus.RUNNING

    def snapshot(self) -> RunnerSnapshot:
        """Non-blocking view of status + captured log.

        Reaps a stuck run first (see :meth:`_reap_if_stuck`) so the
        auto-refreshing activity panel recovers a wedged RUNNING
        status within one poll cycle, without needing the operator to
        click anything.
        """
        self._reap_if_stuck()
        with self._lock:
            return RunnerSnapshot(
                self._status,
                self._description,
                self.log.getvalue(),
                tuple(self._progress.items()),
            )

    def _count_if_fill(self, line: str) -> None:
        """Bump the active broker's fill count if this line confirms a trade."""
        if not is_fill_line(line):
            return
        with self._lock:
            broker = self._current_broker
            if broker is not None:
                self._fill_counts[broker] = (
                    self._fill_counts.get(broker, 0) + 1
                )

    def _apply_progress(self, kind: str, value: str) -> None:
        """Update per-broker progress from an engine PROGRESS sentinel."""
        with self._lock:
            if kind == "PLAN":
                self._progress = {
                    b: "pending" for b in value.split(",") if b
                }
                self._fill_counts = {}
                self._current_broker = None
            elif kind == "START":
                self._progress[value] = "running"
                self._fill_counts[value] = 0
                self._current_broker = value
            elif kind == "DONE":
                # Green only if the broker actually placed an order;
                # otherwise yellow (session was fine but no fills).
                self._progress[value] = (
                    "done" if self._fill_counts.get(value, 0) > 0
                    else "done_no_fill"
                )
                if self._current_broker == value:
                    self._current_broker = None
            elif kind == "FAIL":
                self._progress[value] = "failed"
                if self._current_broker == value:
                    self._current_broker = None

    # --- public operations --------------------------------------------

    def start_holdings(self, broker_keys: list[str]) -> None:
        """Pull balances/holdings for the given brokers (or ['all'])."""
        args = ["holdings", self._brokers_arg(broker_keys)]
        self._start(args, broker_keys, f"Holdings: {', '.join(broker_keys)}")

    def start_account_test(self, broker_key: str, account_index: int) -> None:
        """Login + pull balances for ONE saved account of a broker.

        Used to verify a single (e.g. newly added) account's
        credentials without logging into the broker's other accounts:
        the child env carries only that account's value.
        """
        env = self._vault.build_env_single_account(broker_key, account_index)
        if not env:
            msg = "Save the account first — per-account test uses saved credentials."
            raise ValueError(msg)
        args = ["holdings", self._brokers_arg([broker_key])]
        desc = f"Test {broker_key} account #{account_index + 1}"
        self._start(args, [broker_key], desc, env_override=env)

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
        limit_price: float | None = None,
    ) -> None:
        """Execute a buy/sell.

        ``price_type`` ("market"/"limit") and ``time_in_force``
        ("day"/"gtc") are plumbed onto the StockOrder. ``limit_price``
        is the explicit price for a limit order; when None on a limit
        order the broker derives one via its own native limit logic.
        Brokers that read these honor them; the rest keep their own
        automatic market->limit / sub-$1 fallback. ``dry=True`` is a
        no-op run.
        """
        args = [
            action,
            str(amount),
            ",".join(t.strip() for t in tickers if t.strip()),
            self._brokers_arg(broker_keys),
            "true" if dry else "false",
        ]
        payload = {
            "args": args,
            "price": price_type,
            "time": time_in_force,
            "limit_price": limit_price,
        }
        mode = "DRY" if dry else "LIVE"
        price_desc = price_type
        if price_type == "limit":
            price_desc = f"limit@{limit_price}" if limit_price is not None else "limit@auto"
        desc = (
            f"{mode} {action} {amount} {','.join(tickers)} "
            f"[{price_desc}/{time_in_force}] -> {', '.join(broker_keys)}"
        )
        self._start(payload, broker_keys, desc)

    def start_signal_run(
        self,
        *,
        ticker: str,
        play_key: str,
        split_key: str,
        broker_keys: list[str],
        dry: bool,
    ) -> None:
        """Execute one reverse-split signal: BUY exactly 1 share.

        Quantity is hard-capped at 1 (one whole share captures the
        round-up; never buy more). ``play_key`` is the GUI_QUEUE KEY and
        ``split_key`` the economic identity — both go to the engine env
        so the ledger attributes the run and blocks the same real split
        bought via another feed.
        """
        args = [
            "buy",
            "1",
            ticker.strip().upper(),
            self._brokers_arg(broker_keys),
            "true" if dry else "false",
        ]
        payload = {"args": args, "price": "market", "time": "day", "limit_price": None}
        mode = "DRY" if dry else "LIVE"
        desc = (
            f"{mode} SIGNAL buy 1 {ticker.upper()} "
            f"[{play_key}] -> {', '.join(broker_keys)}"
        )
        self._start(
            payload,
            broker_keys,
            desc,
            extra_env={
                "RSA_PLAY_KEY": play_key,
                "RSA_PLAY_SPLIT_KEY": split_key,
            },
        )

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
        env_override: dict[str, str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            if self._status == RunStatus.RUNNING:
                msg = "A run is already in progress."
                raise RuntimeError(msg)
        # Cross-tab / cross-process guard: only one engine run at a time
        # so two browser tabs can't double-submit (esp. LIVE orders).
        self._acquire_run_lock()
        with self._lock:
            self._status = RunStatus.RUNNING
            self._description = description
            self._cancelled = False
        self.log.clear()
        with self._lock:
            self._progress = {}
            self._fill_counts = {}
            self._current_broker = None
        env_keys = self._resolve_broker_keys(broker_keys)
        # Capture secrets so they're scrubbed from the on-screen and
        # persisted logs if a broker library ever echoes them.
        self._secrets = self._vault.secret_values()
        # Credentials go to the child's environment only. A per-account
        # test passes a pre-built single-account env instead of the
        # broker's full (all-accounts) value.
        broker_env = env_override if env_override is not None else self._vault.build_env(env_keys)
        # Per-signal idempotency keys (RSA_PLAY_KEY / RSA_PLAY_SPLIT_KEY)
        # are layered last so a signal run is attributed and economically
        # de-duplicated in the ledger. Empty for manual runs.
        child_env = {**os.environ, **broker_env, **(extra_env or {})}
        try:
            self._proc = subprocess.Popen(  # noqa: S603
                [sys.executable, "-u", "-m", "src.gui.core.engine_proc", json.dumps(payload)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(_PROJECT_ROOT),
                env=child_env,
            )
        except (OSError, ValueError) as exc:
            # Never leave the runner stuck on RUNNING if the process
            # could not even be launched.
            self.log.write(f"Failed to start engine process: {exc}\n")
            self._release_run_lock()
            self._set_status(RunStatus.ERROR)
            return
        self._record_engine_pid(self._proc.pid)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    # --- single-instance run lock -------------------------------------

    @staticmethod
    def _lock_is_stale() -> bool:
        try:
            info = json.loads(_RUN_LOCK.read_text())
        except (OSError, ValueError):
            return True
        pid = info.get("engine_pid")
        if pid is not None:
            # Live engine for that pid -> not stale.
            return not psutil.pid_exists(int(pid))
        # No engine pid recorded yet (the brief window between acquiring
        # the lock and Popen+record). Anchor liveness to the GUI process
        # that holds the lock: if it's gone, the start was abandoned and
        # the lock is stale immediately — this closes the old hole where
        # a crash in that window wedged ALL runs for _STALE_LOCK_SECONDS
        # (6h). Fall back to the age check only if no owner pid is known.
        owner = info.get("owner_pid")
        if owner is not None:
            return not psutil.pid_exists(int(owner))
        return (time.time() - float(info.get("created", 0))) > _STALE_LOCK_SECONDS

    def _acquire_run_lock(self) -> None:
        _RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(_RUN_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not self._lock_is_stale():
                msg = (
                    "Another AutoRSA run is already in progress (possibly in "
                    "another browser tab). Wait for it to finish or cancel it."
                )
                raise RunBusyError(msg) from None
            with contextlib.suppress(OSError):
                _RUN_LOCK.unlink()
            fd = os.open(_RUN_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            json.dump(
                {"engine_pid": None, "owner_pid": os.getpid(), "created": time.time()},
                fh,
            )

    @staticmethod
    def _record_engine_pid(pid: int) -> None:
        # Atomic tmp+replace (matching the vault) so a crash mid-write
        # can't leave a truncated/corrupt lock file.
        payload = json.dumps(
            {"engine_pid": pid, "owner_pid": os.getpid(), "created": time.time()},
        )
        with contextlib.suppress(OSError):
            tmp = _RUN_LOCK.with_suffix(_RUN_LOCK.suffix + ".tmp")
            tmp.write_text(payload)
            tmp.replace(_RUN_LOCK)

    @staticmethod
    def _release_run_lock() -> None:
        with contextlib.suppress(OSError):
            _RUN_LOCK.unlink()

    @staticmethod
    def _kill_descendants(proc: subprocess.Popen) -> None:
        """Kill any surviving child/grandchild processes of ``proc``.

        Used both by cancel and the stuck-run reaper. Best-effort:
        if the engine already exited its browser children may have
        been re-parented (POSIX) and won't be found here — the
        per-broker cleanups (e.g. chase profile scan) catch those on
        the next run. This at least reaps the common still-attached
        case.
        """
        with contextlib.suppress(psutil.Error, OSError):
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    child.kill()

    def _reap_if_stuck(self) -> None:
        """Finalize a RUNNING status whose engine process has exited.

        The pump reader blocks on ``for raw in proc.stdout``; if a
        leaked browser child holds the pipe's write end open, the
        reader never gets EOF and ``proc.wait()`` (which flips status
        out of RUNNING) is never reached. Detect the engine main
        having exited and finalize directly so the UI's disabled
        buttons re-enable. Idempotent with the pump's own ``finally``.
        """
        with self._lock:
            if self._status != RunStatus.RUNNING:
                return
            proc = self._proc
            thread = self._thread
        if proc is None or proc.poll() is None:
            # No process, or the engine is genuinely still alive — a
            # real run is in progress; leave it be.
            return
        # Engine exited but we're still RUNNING -> wedged reader.
        self.log.write(
            "\n--- engine process exited but the run was still marked "
            "running (a leaked browser likely held the output pipe "
            "open); auto-recovering so the UI unblocks ---\n",
        )
        self._kill_descendants(proc)
        # Nudge the blocked reader to fall through to its finally by
        # closing the pipe it's reading. Best-effort across platforms.
        with contextlib.suppress(Exception):
            if proc.stdout is not None:
                proc.stdout.close()
        # Don't depend on the (possibly permanently-wedged) reader:
        # finalize here too. Both paths are guarded/idempotent.
        if thread is None or not thread.is_alive():
            self._release_run_lock()
            code = proc.returncode
            self._set_status(
                RunStatus.FINISHED if code == 0 else RunStatus.ERROR,
            )

    def cancel(self) -> None:
        """Abort the current run: kill the engine and its browser tree.

        Robust to the case where the engine *main* has already exited
        but a leaked browser child is holding the stdout pipe open
        (which wedges the reader on RUNNING): we kill descendants
        regardless of ``proc.poll()``, close the pipe to unblock the
        reader, and finalize the status directly if the reader can't
        recover on its own.
        """
        with self._lock:
            if self._status != RunStatus.RUNNING:
                return
            self._cancelled = True
            proc = self._proc
            thread = self._thread
        # Unblock the reader if it is waiting on a 2FA answer.
        self.prompts.cancel()
        if proc is not None:
            # Kill leaked browser children even when the engine main
            # has already exited (the old `proc.poll() is None` guard
            # skipped this case, leaving the zombie — and the wedge).
            self._kill_descendants(proc)
            if proc.poll() is None:
                with contextlib.suppress(psutil.Error, OSError):
                    psutil.Process(proc.pid).kill()
            with contextlib.suppress(Exception):
                if proc.stdout is not None:
                    proc.stdout.close()
        self.log.write("\n--- Run cancelled by user ---\n")
        # If the engine already exited (reader may be wedged on a held
        # pipe) or the reader thread is gone, finalize here so the UI
        # unblocks immediately instead of waiting on a dead reader.
        if (
            proc is not None and proc.poll() is not None
        ) or thread is None or not thread.is_alive():
            self._release_run_lock()
            self._set_status(RunStatus.CANCELLED)

    def _pump(self) -> None:  # noqa: C901, PLR0912
        proc = self._proc
        if proc is None or proc.stdout is None:
            self._release_run_lock()
            self._set_status(RunStatus.ERROR)
            return
        discovered: dict[str, list[tuple[str, str]]] = {}
        try:
            for raw in proc.stdout:
                if raw.startswith(PROMPT_SENTINEL):
                    text = raw[len(PROMPT_SENTINEL):].rstrip("\r\n")
                    self.prompts.open(text)
                    answer = self.prompts.wait_answer()
                    if proc.stdin is not None:
                        try:
                            proc.stdin.write(answer + "\n")
                            proc.stdin.flush()
                        except (BrokenPipeError, OSError, ValueError):
                            # The engine exited (e.g. login timed out) while
                            # the user was entering the 2FA code. Don't turn
                            # this benign race into a generic "pump error"
                            # that ends the reader — log it and keep draining
                            # whatever output remains.
                            self.log.write(
                                "(engine exited before the 2FA code was "
                                "submitted)\n",
                            )
                elif raw.startswith(ACCOUNT_SENTINEL):
                    payload = raw[len(ACCOUNT_SENTINEL):].rstrip("\r\n")
                    parts = payload.split("\t", 2)
                    if len(parts) == _DISCOVERY_FIELDS and parts[0] and parts[2]:
                        broker, parent, account = parts
                        discovered.setdefault(broker, []).append(
                            (parent, account),
                        )
                elif raw.startswith(PROGRESS_SENTINEL):
                    kind, _, value = raw[len(PROGRESS_SENTINEL):].rstrip(
                        "\r\n",
                    ).partition("\t")
                    self._apply_progress(kind, value)
                else:
                    self.log.write(self._redact(raw))
                    self._count_if_fill(raw)
        except Exception as exc:
            self.log.write(f"\n--- GUI pump error: {exc} ---\n")
        finally:
            # Persist discovered sub-accounts for the Trade-tab picker.
            for broker, accounts in discovered.items():
                try:
                    self._vault.add_discovered_accounts(broker, accounts)
                except Exception as exc:
                    self.log.write(
                        f"\n(could not store discovered accounts: {exc})\n",
                    )
            code = proc.wait()
            self.prompts.cancel()
            self._release_run_lock()
            with self._lock:
                if self._cancelled:
                    self._status = RunStatus.CANCELLED
                else:
                    self._status = RunStatus.FINISHED if code == 0 else RunStatus.ERROR
                final_status = self._status
            self._write_audit_log(final_status)
            self._notify(final_status)

    def _notify(self, status: RunStatus) -> None:
        """POST a one-line completion message to a configured webhook.

        Runs in the daemon reader thread, so it fires even if the user
        closed the browser tab during a long browser-broker run.
        Best-effort; never raises. The description has no secrets.
        """
        try:
            cfg = self._vault.get_notify()
        except Exception:
            return
        url = (cfg.get("webhook_url") or "").strip()
        if not url:
            return
        msg = f"AutoRSA run {status.value}: {self._description}"
        with contextlib.suppress(Exception):
            requests.post(url, json={"content": msg}, timeout=10)

    def _write_audit_log(self, status: RunStatus) -> None:
        """Persist the run's full output for an audit trail (best-effort).

        Written under creds/run_logs (gitignored with the rest of creds)
        because logs can contain holdings/account data.
        """
        try:
            log_dir = _PROJECT_ROOT / "creds" / "run_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
            (log_dir / f"{stamp}_{status.value}.log").write_text(
                self.log.getvalue(),
                encoding="utf-8",
            )
        except OSError as exc:
            self.log.write(f"\n(could not write audit log: {exc})\n")

    def _set_status(self, status: RunStatus) -> None:
        with self._lock:
            self._status = status
