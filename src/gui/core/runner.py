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

from src.gui.core import holdings as holdings_store
from src.gui.core.engine_proc import (
    ACCOUNT_SENTINEL,
    HOLDINGS_SENTINEL,
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
# How long the engine may be exited while the run is still RUNNING before
# the reaper declares the reader wedged. A healthy pump finalizes within
# milliseconds of EOF, so this only needs to clear that; kept comfortably
# above it so a snapshot landing mid-finally never cries "leaked browser"
# on a clean run. Recovery of a genuine wedge lands within ~1 poll cycle.
_REAP_GRACE_SECONDS = 1.5
# A broker that has been "running" this long without finishing is almost
# certainly waiting on a login/2FA prompt the operator hasn't answered, or
# is hung — surface a hint so a stalled run isn't a silent spinner.
STUCK_BROKER_SECONDS = 90.0
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
    # Per-broker timing, START-ordered: (broker, state, elapsed_seconds).
    # elapsed runs live for a still-"running" broker and freezes at the
    # DONE/FAIL time otherwise. Drives the run timeline + stuck-broker hint.
    timings: tuple[tuple[str, str, float], ...] = ()


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
        # broker -> {"start": monotonic, "end": monotonic|None}. Insertion
        # order is START order, so the timeline renders top-to-bottom.
        self._broker_timings: dict[str, dict[str, float | None]] = {}
        # When the reaper first saw the engine exited while still RUNNING
        # (monotonic seconds); used to grace-period the wedge decision.
        self._engine_exit_seen: float | None = None
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
                self._compute_timings(),
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
                self._broker_timings = {}
            elif kind == "START":
                self._progress[value] = "running"
                self._fill_counts[value] = 0
                self._current_broker = value
                self._broker_timings[value] = {
                    "start": time.monotonic(),
                    "end": None,
                }
            elif kind == "DONE":
                # Green only if the broker actually placed an order;
                # otherwise yellow (session was fine but no fills).
                self._progress[value] = (
                    "done" if self._fill_counts.get(value, 0) > 0
                    else "done_no_fill"
                )
                if self._current_broker == value:
                    self._current_broker = None
                self._stamp_broker_end(value)
            elif kind == "FAIL":
                self._progress[value] = "failed"
                if self._current_broker == value:
                    self._current_broker = None
                self._stamp_broker_end(value)

    def _stamp_broker_end(self, broker: str) -> None:
        """Freeze a broker's elapsed timer at its DONE/FAIL moment.

        Caller holds ``self._lock``. No-op if the broker never emitted a
        START (defensive against out-of-order sentinels).
        """
        timing = self._broker_timings.get(broker)
        if timing is not None and timing.get("end") is None:
            timing["end"] = time.monotonic()

    def _compute_timings(self) -> tuple[tuple[str, str, float], ...]:
        """Build the (broker, state, elapsed) timeline. Caller holds the lock."""
        now = time.monotonic()
        out: list[tuple[str, str, float]] = []
        for broker, t in self._broker_timings.items():
            start = t.get("start")
            if start is None:
                continue
            end = t.get("end")
            elapsed = (end if end is not None else now) - start
            state = self._progress.get(broker, "pending")
            out.append((broker, state, round(elapsed, 1)))
        return tuple(out)

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
            # Null the proc here, under the same lock as the RUNNING
            # flip. Otherwise _reap_if_stuck (called by the 2s activity
            # fragment's snapshot()) could see RUNNING + the PREVIOUS
            # run's dead proc during the Popen window below and wrongly
            # reap a run that's still starting. With proc=None the
            # reaper returns early until the real proc is recorded.
            self._proc = None
            # Fresh run: forget any prior run's engine-exit timestamp so
            # the wedge grace period starts clean.
            self._engine_exit_seen = None
        self.log.clear()
        with self._lock:
            self._progress = {}
            self._fill_counts = {}
            self._current_broker = None
        env_keys = self._resolve_broker_keys(broker_keys)
        try:
            # Capture secrets so they're scrubbed from the on-screen and
            # persisted logs if a broker library ever echoes them.
            self._secrets = self._vault.secret_values()
            # Credentials go to the child's environment only. A per-account
            # test passes a pre-built single-account env instead of the
            # broker's full (all-accounts) value.
            broker_env = (
                env_override
                if env_override is not None
                else self._vault.build_env(env_keys)
            )
            # Per-signal idempotency keys (RSA_PLAY_KEY / RSA_PLAY_SPLIT_KEY)
            # are layered last so a signal run is attributed and
            # economically de-duplicated in the ledger. Empty for manual.
            child_env = {**os.environ, **broker_env, **(extra_env or {})}
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
        except Exception as exc:  # noqa: BLE001
            # ANY failure building the child env or launching the engine
            # (vault re-locked between click and start, a decrypt/KeyError,
            # an OSError, a bad Popen) must NOT leave the runner wedged on
            # RUNNING with the lock still held — that kills all trading
            # until Streamlit restarts. Release and finalize to ERROR.
            # (secret_values()/build_env() used to run outside this guard.)
            self.log.write(f"Failed to start engine process: {exc}\n")
            self._release_run_lock()
            self._set_status(RunStatus.ERROR)
            return
        self._record_engine_pid(self._proc.pid)
        # If cancel() landed during the env-build / Popen window above
        # (when _proc was still None, so cancel could only set the flag),
        # honor it now: kill the just-launched engine instead of letting
        # the LIVE order run to completion while the operator believes
        # they cancelled.
        with self._lock:
            cancelled_during_start = self._cancelled
            proc = self._proc
        if cancelled_during_start and proc is not None:
            self._kill_descendants(proc)
            with contextlib.suppress(psutil.Error, OSError):
                psutil.Process(proc.pid).kill()
            with contextlib.suppress(Exception):
                if proc.stdout is not None:
                    proc.stdout.close()
            self.log.write("\n--- Run cancelled during startup ---\n")
            if self._finalize(proc, RunStatus.CANCELLED):
                self._post_finalize(RunStatus.CANCELLED)
            return
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    # --- single-instance run lock -------------------------------------

    @staticmethod
    def _engine_pid_state(pid: object) -> str:
        """Classify a recorded engine pid: engine | other | dead | unknown.

        Guards against PID *reuse*: after a crash/reboot the recorded
        ``engine_pid`` may have been recycled by the OS for an unrelated
        process, which a bare ``pid_exists`` would call "alive" and wedge
        every run forever. We inspect the cmdline to confirm it's really
        an engine. "unknown" = the pid exists but we can't read it
        (permissions) — the caller must stay conservative there so a
        genuinely-live run is never treated as stale (double-submit).
        """
        try:
            cmdline = " ".join(psutil.Process(int(pid)).cmdline())
        except psutil.NoSuchProcess:
            return "dead"
        except (psutil.Error, OSError, ValueError):
            return "unknown"
        return "engine" if "engine_proc" in cmdline else "other"

    @staticmethod
    def _lock_is_stale() -> bool:
        try:
            info = json.loads(_RUN_LOCK.read_text())
        except (OSError, ValueError):
            return True
        aged_out = (time.time() - float(info.get("created", 0) or 0)) > _STALE_LOCK_SECONDS
        pid = info.get("engine_pid")
        if pid is not None:
            state = TradeRunner._engine_pid_state(pid)
            if state == "engine":
                return False  # a real engine is alive -> genuine run
            if state in {"dead", "other"}:
                return True  # engine gone or its pid was reused -> reclaim
            # "unknown": exists but uninspectable — don't risk clobbering a
            # live run; only reclaim once it has aged out.
            return aged_out
        # No engine pid recorded yet (the brief window between acquiring
        # the lock and Popen+record). Anchor liveness to the GUI process
        # that holds the lock: if it's gone, the start was abandoned and
        # the lock is stale immediately — this closes the old hole where
        # a crash in that window wedged ALL runs for _STALE_LOCK_SECONDS
        # (6h). Fall back to the age check only if no owner pid is known.
        owner = info.get("owner_pid")
        if owner is not None:
            return not psutil.pid_exists(int(owner))
        return aged_out

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

    def _finalize(self, proc: subprocess.Popen | None, status: RunStatus) -> bool:
        """Move a RUNNING run to a terminal ``status`` and drop its lock.

        Guarded by process identity: the mutation only happens if
        ``proc`` is *still* the active run's process and the run is
        still RUNNING. That guard is what lets the wedged-reader reaper,
        the cancel path, and the pump's own ``finally`` all race to
        finalize the same run without a stale one ever clobbering a
        *newer* run that already took over (``_start`` installs a fresh
        proc). Returns whether this call performed the finalize, so the
        caller can do the once-only audit/notify. Idempotent per proc.
        """
        if proc is None:
            return False
        with self._lock:
            if self._status != RunStatus.RUNNING or self._proc is not proc:
                return False
            self._status = status
        self._release_run_lock()
        return True

    def _post_finalize(self, status: RunStatus) -> None:
        """Audit-log the finished run and fire the completion webhook.

        The webhook is dispatched on a short daemon thread: the reaper
        and cancel both run on Streamlit's UI thread, and a slow/hanging
        webhook endpoint (``requests.post`` up to 10s) must never freeze
        the UI. The audit log is a fast local write, so it stays inline.
        """
        self._write_audit_log(status)
        threading.Thread(
            target=self._notify, args=(status,), daemon=True,
        ).start()

    def _terminal_status(self, code: int | None, *, cancelled: bool) -> RunStatus:
        """Map an exit code + per-broker progress to a terminal status.

        The engine exits 0 even when *every* broker failed — each
        per-broker error is caught and the run continues — so a bare
        ``code == 0`` would report a green FINISHED and fire a
        "run finished" webhook for a run where nothing was bought. When
        the progress map shows failures and not a single success, call it
        ERROR so the top-line status and the completion webhook don't
        misreport a total failure as success.
        """
        if cancelled:
            return RunStatus.CANCELLED
        if code != 0:
            return RunStatus.ERROR
        with self._lock:
            states = list(self._progress.values())
        any_failed = any(s == "failed" for s in states)
        any_ok = any(s in {"done", "done_no_fill"} for s in states)
        if states and any_failed and not any_ok:
            return RunStatus.ERROR
        return RunStatus.FINISHED

    def _reap_if_stuck(self) -> None:
        """Finalize a RUNNING status whose engine process has exited.

        The pump reader blocks on ``for raw in proc.stdout``; if a
        leaked browser child holds the pipe's write end open, the
        reader never gets EOF and ``proc.wait()`` (which flips status
        out of RUNNING) is never reached. Detect the engine main having
        exited and finalize directly so the UI's disabled buttons
        re-enable.

        Crucially this does **not** wait for the reader thread to die
        first. That thread can be blocked forever: killing the leaked
        descendant can miss a re-parented browser, and closing the pipe
        from another thread does not reliably interrupt a blocked
        ``read()``. Gating recovery on ``not thread.is_alive()`` (as an
        earlier version did) therefore left the run wedged on RUNNING
        indefinitely — every Execute/Confirm button disabled and Cancel
        unable to help. :meth:`_finalize`'s proc-identity guard makes
        finalizing-without-the-reader safe: if the wedged reader ever
        does wake up, its own ``_finalize`` is a no-op, and a newer run
        is never clobbered.

        A short grace period (:data:`_REAP_GRACE_SECONDS`) separates the
        genuine wedge from the sub-second window where a *healthy* pump
        has just seen EOF and is about to finalize on its own — without
        it, a snapshot landing in that window would print a misleading
        "leaked browser" recovery on a perfectly clean run.
        """
        with self._lock:
            if self._status != RunStatus.RUNNING:
                self._engine_exit_seen = None
                return
            proc = self._proc
        if proc is None or proc.poll() is None:
            # No process, or the engine is genuinely still alive — a
            # real run is in progress; leave it be (and reset the timer).
            with self._lock:
                self._engine_exit_seen = None
            return
        # Engine has exited but the run is still RUNNING. Give the pump's
        # own finally the grace period to finalize cleanly first; only
        # past it do we treat the still-alive reader as truly wedged.
        now = time.monotonic()
        with self._lock:
            if self._engine_exit_seen is None:
                self._engine_exit_seen = now
            waited = now - self._engine_exit_seen
        if waited < _REAP_GRACE_SECONDS:
            return
        # Engine exited and stayed unfinalized past the grace -> wedged.
        self.log.write(
            "\n--- engine process exited but the run was still marked "
            "running (a leaked browser likely held the output pipe "
            "open); auto-recovering so the UI unblocks ---\n",
        )
        self._kill_descendants(proc)
        # Nudge the blocked reader to fall through to its finally by
        # closing the pipe it's reading. Best-effort across platforms —
        # we finalize below regardless of whether this wakes it.
        with contextlib.suppress(Exception):
            if proc.stdout is not None:
                proc.stdout.close()
        with self._lock:
            cancelled = self._cancelled
        status = self._terminal_status(proc.returncode, cancelled=cancelled)
        if self._finalize(proc, status):
            self._post_finalize(status)

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
        # Finalize immediately so the UI unblocks on the very next
        # rerun, instead of waiting on a reader thread that may be
        # permanently wedged on a leaked browser's pipe. The
        # proc-identity guard means we never clobber a newer run; if
        # proc is None (a run still mid-start) we leave the _cancelled
        # flag set for the pump/reaper to honor.
        if self._finalize(proc, RunStatus.CANCELLED):
            self._post_finalize(RunStatus.CANCELLED)

    def _pump(self) -> None:  # noqa: C901, PLR0912
        proc = self._proc
        if proc is None or proc.stdout is None:
            self._release_run_lock()
            self._set_status(RunStatus.ERROR)
            return
        discovered: dict[str, list[tuple[str, str]]] = {}
        captured_holdings: list[dict] = []
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
                elif raw.startswith(HOLDINGS_SENTINEL):
                    payload = raw[len(HOLDINGS_SENTINEL):].rstrip("\r\n")
                    parsed = holdings_store.parse_line(payload)
                    if parsed is not None:
                        captured_holdings.append(parsed)
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
            # Persist the structured holdings snapshot for the Balances
            # dashboard + reconciliation (merged per broker; a no-op when
            # this run captured none, so a trade run never wipes it).
            if captured_holdings:
                try:
                    holdings_store.save_positions(
                        captured_holdings,
                        captured_at=datetime.datetime.now(
                            datetime.UTC,
                        ).isoformat(timespec="seconds"),
                    )
                except Exception as exc:
                    self.log.write(
                        f"\n(could not store holdings snapshot: {exc})\n",
                    )
            code = proc.wait()
            self.prompts.cancel()
            with self._lock:
                cancelled = self._cancelled
            status = self._terminal_status(code, cancelled=cancelled)
            # Finalize through the shared, proc-identity-guarded path so
            # a reaper/cancel that already recovered this run (its reader
            # was wedged) isn't double-finalized here. If _finalize
            # returns False the run was already finalized elsewhere and
            # its audit/notify already fired, so we skip ours.
            if self._finalize(proc, status):
                self._post_finalize(status)

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
        msg = f"AutoRSA run {status.value}: {self._description}{self._broker_summary()}"
        with contextlib.suppress(Exception):
            requests.post(url, json={"content": msg}, timeout=10)

    def _broker_summary(self) -> str:
        """Per-broker pass/fail tail for the webhook, e.g. ' [2 ok, 1 failed]'.

        So the completion webhook — read by an operator who may have
        closed the tab — reflects what actually happened per broker, not
        just the top-line status. Empty when the run emitted no progress.
        """
        with self._lock:
            states = list(self._progress.values())
        if not states:
            return ""
        ok = sum(1 for s in states if s in {"done", "done_no_fill"})
        failed = sum(1 for s in states if s == "failed")
        parts = []
        if ok:
            parts.append(f"{ok} ok")
        if failed:
            parts.append(f"{failed} failed")
        return f" [{', '.join(parts)}]" if parts else ""

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
