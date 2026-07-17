"""Parallel broker execution driver — the engine behind "Trade Beta".

This is a SEPARATE path from :func:`src.auto_rsa.fun_run`; that sequential
function is left completely untouched so the working Trade tab can never
be affected by anything here. Only the Beta tab reaches this module (via
``RSA_PARALLEL=1`` / a payload flag in the engine subprocess).

Design (see the Trade Beta decisions):
* API brokers (bbae, dspac, fennel, public, robinhood, schwab, …) run
  CONCURRENTLY, bounded by a cap.
* Browser/interactive brokers (chase, fidelity, sofi, wellsfargo,
  vanguard, tornado) run SEQUENTIALLY — concurrent browser sessions and
  their 2FA flows are the risky part, so they are serialized.
* Any 2FA/OTP ``input()`` is serialized process-wide by ``_INPUT_LOCK``
  in engine_proc, so even a concurrent API broker that prompts can't
  scramble the shared stdin — prompts are answered one at a time.

Thread-safety of the ``StockOrder``: the sequential fun_run mutates a
single shared order — ``order_validate`` rewrites shared lists, and some
brokers (notably firstrade and webull) temporarily rewrite the order's
``amount``/``action``/``price`` mid-order and restore them in a
``finally``. Sequentially that's safe; concurrently it is NOT — another
broker reads those same fields to size its live order and could see the
transient wrong value and place a wrong-size/wrong-side REAL order. So
each concurrent broker gets its OWN order (:func:`_thread_local_order`, a
shallow copy that isolates the scalar reassignments per thread), and the
order is validated ONCE up front (never per-broker in parallel).

BETA CAVEAT: the underlying broker libraries were written for sequential
use and may hold module-level session globals; running two *different*
brokers at once is expected to be fine (distinct libraries), but this has
not been proven across every broker. Validate in your own environment
(dry-run first) before trusting a live parallel run.
"""

from __future__ import annotations

import copy
import threading
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the broker deps at module import time
    from collections.abc import Callable

# Brokers that must run one-at-a-time (browser automation and/or
# interactive login). Matched on the lowercased broker key.
_SEQUENTIAL_BROKERS = frozenset(
    {"chase", "fidelity", "sofi", "wellsfargo", "vanguard", "tornado"},
)
# Extra head-room over the per-broker watchdog before we give up joining a
# concurrent API worker (API brokers have no internal watchdog like the
# ThreadHandler browser path does).
_JOIN_GRACE_SECONDS = 30.0


def _auto():
    """Lazily import src.auto_rsa (pulls in the broker libraries)."""
    from src import auto_rsa  # noqa: PLC0415

    return auto_rsa


def _broker_key(broker_info: object) -> str:
    return str(broker_info.name).lower()  # type: ignore[attr-defined]


def _thread_local_order(order_obj: object) -> object:
    """Return a per-thread copy of the StockOrder for one broker.

    CRITICAL for real money: concurrent brokers must NOT share one order.
    firstrade/webull temporarily rewrite ``amount``/``action``/``price``
    on the order mid-place (a lot-size "dance") and restore them in a
    ``finally``; every other broker reads those same fields to size its
    live order. On a shared order a concurrent broker can read the
    transient value (e.g. amount 100, action "sell") and place a
    wrong-size / wrong-side REAL order. A shallow copy isolates those
    scalar reassignments — each ``set_amount``/``set_action`` writes the
    copy's own attribute, not the shared one. We do NOT deepcopy: the
    order's logged-in map holds live broker/session objects.
    """
    return copy.copy(order_obj)


def run_broker(
    broker_info: object,
    order_obj: object,
    bot_obj: object = None,
    loop: object = None,
    *,
    docker_mode: bool = False,
) -> tuple[bool, float]:
    """Run ONE broker's full flow. Returns ``(failed, broker_total)``.

    Mirrors the per-broker body of :func:`src.auto_rsa.fun_run` exactly,
    but isolated so it can run in its own thread and does NOT call
    ``order_validate`` (done once up front by the caller). Emits its own
    START/DONE/FAIL progress and never raises — a broker failure is
    returned as ``failed=True`` so one broker can't abort the others.
    """
    a = _auto()
    b = a.BrokerName
    broker = _broker_key(broker_info)
    broker_failed = False
    broker_total = 0.0
    a._emit_progress("START", broker)
    try:
        success = None
        th = None
        name = broker_info.name  # type: ignore[attr-defined]
        # --- init dispatch (mirrors fun_run) ---------------------------
        if name == b.BBAE:
            success = a.bbae_init(bot_obj=bot_obj, loop=loop)
        elif name == b.CHASE:
            th = a.ThreadHandler(a.chase_run, order_obj=order_obj, bot_obj=bot_obj, loop=loop)
        elif name == b.DSPAC:
            success = a.dspac_init(bot_obj=bot_obj, loop=loop)
        elif name == b.FENNEL:
            success = a.fennel_init(loop=loop)
        elif name == b.FIDELITY:
            th = a.ThreadHandler(a.fidelity_run, order_obj=order_obj, bot_obj=bot_obj, loop=loop)
        elif name == b.FIRSTRADE:
            success = a.firstrade_init(bot_obj=bot_obj, loop=loop)
        elif name == b.PUBLIC:
            success = a.public_init(loop=loop)
        elif name == b.ROBINHOOD:
            success = a.robinhood_init(loop=loop)
        elif name == b.SCHWAB:
            success = a.schwab_init()
        elif name == b.SOFI:
            th = a.ThreadHandler(a.sofi_run, order_obj=order_obj, bot_obj=bot_obj, loop=loop)
        elif name == b.TASTYTRADE:
            success = a.tastytrade_init()
        elif name == b.TORNADO:
            success = a.tornado_init(docker_mode=docker_mode, loop=loop)
        elif name == b.TRADIER:
            success = a.tradier_init()
        elif name == b.VANGUARD:
            th = a.ThreadHandler(a.vanguard_run, order_obj=order_obj, bot_obj=bot_obj, loop=loop)
        elif name == b.WEBULL:
            success = a.webull_init()
        elif name == b.WELLS_FARGO:
            success = a.wellsfargo_init(bot_obj=bot_obj, docker_mode=docker_mode, loop=loop)

        # --- browser brokers do everything inside their *_run thread ----
        if th is not None:
            th.start()
            th.join(timeout=a._broker_timeout())
            if th.is_alive():
                msg = (
                    f"Error in {broker}: timed out after "
                    f"{a._broker_timeout()}s (broker stuck — abandoned; "
                    f"other brokers continue)"
                )
                raise RuntimeError(msg)
            _, err = th.get_result()
            if err is not None:
                msg = f"Error in {broker}: Function did not complete successfully: {err}"
                raise RuntimeError(msg)
            return (False, 0.0)

        if success is None:
            msg = f"Error in {broker}: Function did not complete successfully"
            raise RuntimeError(msg)

        order_obj.set_logged_in(success, broker)  # type: ignore[attr-defined]
        print()
        logged_in_broker = order_obj.get_logged_in(broker)  # type: ignore[attr-defined]
        if logged_in_broker is None:
            print(f"Error: {broker} not logged in, skipping...")
            return (False, 0.0)

        if order_obj.get_holdings():  # type: ignore[attr-defined]
            _dispatch_holdings(a, b, name, logged_in_broker, loop)
            broker_total = sum(
                acct["total"]
                for acct in order_obj.get_logged_in(broker).get_account_totals().values()  # type: ignore[attr-defined]
            )
            a.print_and_discord(
                f"Total Value of {broker.title()} Accounts: "
                f"${format(broker_total, '0.2f')}",
                loop,
            )
        else:
            _dispatch_transaction(a, b, name, logged_in_broker, order_obj, loop)
            a.print_and_discord(
                f"All {broker.capitalize()} transactions complete", loop,
            )
    except Exception as ex:  # noqa: BLE001 — one broker must never abort the rest
        print(traceback.format_exc())
        print(f"Error with {broker}: {ex}")
        broker_failed = True
    finally:
        a._emit_progress("FAIL" if broker_failed else "DONE", broker)
        print()
    return (broker_failed, broker_total)


def _dispatch_holdings(a, b, name, logged_in_broker, loop) -> None:  # noqa: ANN001
    table: dict = {
        b.BBAE: a.bbae_holdings,
        b.DSPAC: a.dspac_holdings,
        b.FENNEL: a.fennel_holdings,
        b.FIRSTRADE: a.firstrade_holdings,
        b.PUBLIC: a.public_holdings,
        b.ROBINHOOD: a.robinhood_holdings,
        b.SCHWAB: a.schwab_holdings,
        b.TASTYTRADE: a.tastytrade_holdings,
        b.TORNADO: a.tornado_holdings,
        b.TRADIER: a.tradier_holdings,
        b.WEBULL: a.webull_holdings,
        b.WELLS_FARGO: a.wellsfargo_holdings,
    }
    fn: Callable | None = table.get(name)
    if fn is not None:
        fn(logged_in_broker, loop)


def _dispatch_transaction(a, b, name, logged_in_broker, order_obj, loop) -> None:  # noqa: ANN001
    table: dict = {
        b.BBAE: a.bbae_transaction,
        b.DSPAC: a.dspac_transaction,
        b.FENNEL: a.fennel_transaction,
        b.FIRSTRADE: a.firstrade_transaction,
        b.PUBLIC: a.public_transaction,
        b.ROBINHOOD: a.robinhood_transaction,
        b.SCHWAB: a.schwab_transaction,
        b.TASTYTRADE: a.tastytrade_transaction,
        b.TORNADO: a.tornado_transaction,
        b.TRADIER: a.tradier_transaction,
        b.WEBULL: a.webull_transaction,
        b.WELLS_FARGO: a.wellsfargo_transaction,
    }
    fn: Callable | None = table.get(name)
    if fn is not None:
        fn(logged_in_broker, order_obj, loop)


def fun_run_parallel(
    order_obj: object,
    bot_obj: object = None,
    loop: object = None,
    *,
    docker_mode: bool = False,
    cap: int | None = None,
) -> None:
    """Run each broker like fun_run, but API brokers concurrently.

    Browser/interactive brokers run sequentially first, then API brokers
    run concurrently bounded by ``cap`` (default: all at once). Progress
    sentinels and the ledger stay identical to the sequential path.
    """
    a = _auto()
    brokers = [
        bi
        for bi in order_obj.get_brokers()  # type: ignore[attr-defined]
        if bi not in order_obj.get_notbrokers()  # type: ignore[attr-defined]
    ]
    a._emit_progress("PLAN", ",".join(_broker_key(bi) for bi in brokers))

    # Kill-switch / license preflight — same gate as the sequential path.
    # Refuses a real order run when killed / revoked / (Friend build)
    # unlicensed. Holdings and dry runs pass through. Self-contained (not
    # routed through the mockable auto module) and fail-open on any error.
    blocked, kill_msg = False, ""
    try:
        if not (order_obj.get_holdings() or order_obj.get_dry()):  # type: ignore[attr-defined]
            from src.license import _keys  # noqa: PLC0415
            from src.license.client import pre_trade_block  # noqa: PLC0415

            blocked, kill_msg = pre_trade_block(
                require_license=bool(getattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False)),
            )
    except Exception:  # noqa: BLE001 -- fail open; never block on a gate error
        blocked, kill_msg = False, ""
    if blocked:
        print("=" * 60)
        print("ORDER PLACEMENT IS PAUSED BY THE OPERATOR (remote kill switch).")
        if kill_msg:
            print(kill_msg)
        print("No orders were placed.")
        print("=" * 60)
        a._emit_progress("KILL", kill_msg or "paused by operator")
        return
    # Fresh per-broker sub-account counters for this run's Friend-tier cap.
    from src.helper_api import reset_subaccount_caps  # noqa: PLC0415

    reset_subaccount_caps()

    # Validate + clean the order ONCE, before any concurrency, because
    # order_validate mutates shared lists (unsafe to run per-broker in
    # parallel). pre_login=True: nothing is logged in yet.
    try:
        order_obj.order_validate(pre_login=True)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        print(f"Order validation failed — aborting parallel run: {exc}")
        for bi in brokers:
            a._emit_progress("FAIL", _broker_key(bi))
        return

    # Pristine snapshot of the CLEAN order, taken before any broker runs,
    # so per-broker copies can't inherit a mutation from an earlier broker.
    pristine = _thread_local_order(order_obj)

    concurrent = [bi for bi in brokers if _broker_key(bi) not in _SEQUENTIAL_BROKERS]
    sequential = [bi for bi in brokers if _broker_key(bi) in _SEQUENTIAL_BROKERS]

    results: list[tuple[bool, float]] = []

    print(
        f"\n[parallel] {len(concurrent)} API broker(s) run concurrently FIRST, "
        f"then {len(sequential)} browser broker(s) one-at-a-time.\n",
    )

    # 1) API brokers first: concurrent, bounded by `cap`. Each gets its OWN
    # order copy so firstrade/webull's mid-order amount/action rewrites
    # can't be read by a sibling broker sizing a real order.
    if concurrent:
        limit = cap if cap and cap > 0 else len(concurrent)
        sem = threading.Semaphore(min(limit, len(concurrent)))
        out: dict[str, tuple[bool, float]] = {}
        threads: list[tuple[object, threading.Thread]] = []

        def _worker(broker_info: object) -> None:
            with sem:
                out[_broker_key(broker_info)] = run_broker(
                    broker_info, _thread_local_order(pristine), bot_obj, loop,
                    docker_mode=docker_mode,
                )

        for bi in concurrent:
            t = threading.Thread(target=_worker, args=(bi,), daemon=True)
            t.start()
            threads.append((bi, t))
        for bi, t in threads:
            t.join(timeout=a._broker_timeout() + _JOIN_GRACE_SECONDS)
            key = _broker_key(bi)
            if t.is_alive() and key not in out:
                # A concurrent broker overran its watchdog. Its order may
                # still be in flight, so this is AMBIGUOUS, not a clean
                # fail: say so loudly and mark FAIL (red) so the operator
                # verifies with reconciliation. The daemon thread dies with
                # the process; the ledger row (INTENDED/EXECUTED) still
                # blocks any double-buy on a retry.
                print(
                    f"⚠️ {key}: overran the parallel watchdog — abandoned. Its "
                    "order may still be in flight; VERIFY with 'Order "
                    "reconciliation' (Diagnostics) before assuming it failed.",
                )
                a._emit_progress("FAIL", key)
                out[key] = (True, 0.0)
        results.extend(out.get(_broker_key(bi), (True, 0.0)) for bi in concurrent)

    # 2) Browser/interactive brokers last: strictly one at a time (after
    # all the fast API work is done).
    for bi in sequential:
        results.append(
            run_broker(
                bi, _thread_local_order(pristine), bot_obj, loop,
                docker_mode=docker_mode,
            ),
        )

    total_value = sum(bt for _failed, bt in results)
    if order_obj.get_holdings():  # type: ignore[attr-defined]
        a.print_and_discord(
            f"Combined Total Value Across Brokers: "
            f"${format(total_value, '0.2f')}",
            loop,
        )
    a.print_and_discord("All commands complete in all brokers", loop)
