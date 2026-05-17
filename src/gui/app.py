"""Streamlit view layer for the AutoRSA GUI.

This file is intentionally thin: all state and logic live in
``src.gui.core``. It renders tabs for connection status, credential
management, trading, and balances, plus a live console that surfaces 2FA
prompts in the browser.

Run with:  uv run streamlit run src/gui/app.py
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from src.gui.core.brokers_meta import SUPPORTED_BROKERS, BrokerMeta, get_broker
from src.gui.core.results import group_by_broker
from src.gui.core.runner import RunBusyError, RunStatus, TradeRunner
from src.gui.core.tickers import normalize_and_validate
from src.gui.core.totp import normalize_totp_secret
from src.gui.core.vault import Vault, VaultError

st.set_page_config(page_title="AutoRSA GUI", page_icon="📈", layout="wide")


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
def _state() -> None:
    if "vault" not in st.session_state:
        st.session_state.vault = Vault()
    if "runner" not in st.session_state:
        st.session_state.runner = None


def _get_vault() -> Vault:
    return st.session_state.vault


def _get_runner() -> TradeRunner:
    if st.session_state.runner is None:
        st.session_state.runner = TradeRunner(_get_vault())
    return st.session_state.runner


# --------------------------------------------------------------------------
# Sidebar: vault lock/unlock + settings
# --------------------------------------------------------------------------
def _sidebar() -> None:  # noqa: C901, PLR0912, PLR0915
    vault = _get_vault()
    st.sidebar.title("🔐 Vault")

    if not vault.is_initialized():
        st.sidebar.info("No vault yet. Set a master password to create one.")
        pw1 = st.sidebar.text_input("New master password", type="password", key="init_pw1")
        pw2 = st.sidebar.text_input("Confirm password", type="password", key="init_pw2")
        if st.sidebar.button("Create vault", width="stretch"):
            if pw1 != pw2:
                st.sidebar.error("Passwords do not match.")
            else:
                try:
                    vault.initialize(pw1)
                    st.sidebar.success("Vault created and unlocked.")
                    st.rerun()
                except VaultError as exc:
                    st.sidebar.error(str(exc))
        return

    if not vault.is_unlocked():
        st.sidebar.warning("Vault is locked.")
        pw = st.sidebar.text_input("Master password", type="password", key="unlock_pw")
        if st.sidebar.button("Unlock", width="stretch"):
            try:
                vault.unlock(pw)
                st.rerun()
            except VaultError as exc:
                st.sidebar.error(str(exc))
        return

    st.sidebar.success("Vault unlocked.")
    if st.sidebar.button("Lock vault", width="stretch"):
        vault.lock()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("Run settings")
    settings = vault.get_settings()
    headless = st.sidebar.checkbox(
        "Headless browsers (Chase/Fidelity/Wells Fargo)",
        value=settings.get("HEADLESS", "true") == "true",
        help="Keep on. These brokers log in without showing a window; "
        "2FA codes are requested in the Console tab.",
    )
    sort_brokers = st.sidebar.checkbox(
        "Alphabetize brokers",
        value=settings.get("SORT_BROKERS", "true") == "true",
    )
    new_settings = {
        "HEADLESS": "true" if headless else "false",
        "SORT_BROKERS": "true" if sort_brokers else "false",
    }
    if new_settings != settings:
        vault.set_settings(new_settings)

    st.sidebar.divider()
    with st.sidebar.expander("Notifications"):
        notify = vault.get_notify()
        hook = st.text_input(
            "Completion webhook URL (Discord-compatible, optional)",
            value=notify.get("webhook_url", ""),
            help="Posted when a run finishes — fires even if you close "
            "the browser tab during a long browser-broker run.",
            key="notify_hook",
        )
        if st.button("Save notifications"):
            vault.set_notify({"webhook_url": hook.strip()})
            st.success("Notification settings saved.")

    st.sidebar.divider()
    with st.sidebar.expander("Change master password"):
        old = st.text_input("Current", type="password", key="cp_old")
        new = st.text_input("New", type="password", key="cp_new")
        if st.button("Update password"):
            try:
                vault.change_password(old, new)
                st.success("Password changed.")
            except VaultError as exc:
                st.error(str(exc))


# --------------------------------------------------------------------------
# Status tab
# --------------------------------------------------------------------------
def _tab_status() -> None:
    vault = _get_vault()
    st.subheader("Connection & Status")

    col1, col2, col3 = st.columns(3)
    col1.metric("Vault", "Unlocked" if vault.is_unlocked() else "Locked")
    if vault.is_unlocked():
        configured = vault.configured_broker_keys()
        col2.metric("Brokers configured", len(configured))
    else:
        col2.metric("Brokers configured", "—")
    col3.metric("Supported brokers", len(SUPPORTED_BROKERS))

    st.markdown("#### Engine check")
    st.caption(
        "Verifies the GUI can import the AutoRSA trading engine "
        "(brokers, Selenium, etc.).",
    )
    if st.button("Run engine import check"):
        with st.spinner("Importing engine…"):
            try:
                import src.auto_rsa  # noqa: F401, PLC0415

                st.success("Engine imported successfully. GUI is connected.")
            except Exception as exc:
                st.error(f"Engine import failed: {exc}")

    st.markdown("#### Supported brokers")
    configured = set(vault.configured_broker_keys()) if vault.is_unlocked() else set()
    rows = [
        {
            "Broker": meta.display_name,
            "Env var": meta.env_var,
            "Browser-based": "Yes" if meta.browser_based else "No",
            "Configured": "✅" if meta.key in configured else "—",
        }
        for meta in SUPPORTED_BROKERS
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.info(
        "Ally is not supported by this repository and is intentionally absent. "
        "Multi-user login is planned for a later revision.",
    )


# --------------------------------------------------------------------------
# Credentials tab
# --------------------------------------------------------------------------
def _tab_credentials() -> None:
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Credentials")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar to manage credentials.")
        return

    st.caption(
        "Credentials are encrypted at rest with your master password. "
        "No .env file is written; they are only exposed to the broker "
        "scripts in memory during a run.",
    )

    with st.expander("Import from an existing .env file"):
        st.caption(
            "Reads broker variables from a .env in the project root and "
            "stores them in the encrypted vault verbatim (a password "
            "containing ':' is preserved, not reverse-parsed).",
        )
        if st.button("Import .env now"):
            try:
                imported = vault.import_env_file(Path(".env"))
            except VaultError as exc:
                st.error(str(exc))
            else:
                if imported:
                    st.success("Imported: " + ", ".join(sorted(imported)))
                    st.rerun()
                else:
                    st.info("No supported broker variables found in .env.")

    for meta in SUPPORTED_BROKERS:
        _render_broker_credentials(meta, vault, runner)


def _normalize_accounts_totp(accounts: list[dict[str, str]]) -> str | None:
    """Validate/normalize any totp_secret in-place; return an error or None."""
    for i, acc in enumerate(accounts):
        if "totp_secret" in acc:
            norm, err = normalize_totp_secret(acc["totp_secret"])
            if err:
                return f"Account {i + 1} TOTP secret: {err}"
            acc["totp_secret"] = norm if norm is not None else ""
    return None


def _render_account_tests(
    meta: BrokerMeta, accounts: list[dict[str, str]], runner: TradeRunner,
) -> None:
    """Per-account 'Test login' buttons (one saved account at a time)."""
    hint_spec = next((s for s in meta.fields if not s.secret), None)
    st.caption(
        "Test a single account (uses saved credentials — Save first "
        "after adding one):",
    )
    for i, acc in enumerate(accounts):
        hint = ""
        if hint_spec:
            raw_hint = (acc.get(hint_spec.key) or "").strip()
            if raw_hint:
                hint = f" — {raw_hint[:20]}"
        if st.button(
            f"Test account {i + 1}{hint}",
            key=f"testacct_{meta.key}_{i}",
            disabled=runner.is_running(),
        ):
            try:
                runner.start_account_test(meta.key, i)
            except (RunBusyError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.rerun()


def _render_broker_credentials(meta: BrokerMeta, vault: Vault, runner: TradeRunner) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Render one broker's multi-account credential form + controls."""
    accounts = vault.get_broker_accounts(meta.key)
    raw_set = bool(vault.get_broker_raw(meta.key))
    configured = raw_set or bool(accounts and meta.assemble_env_value(accounts))
    label = f"{'✅ ' if configured else ''}{meta.display_name}"
    with st.expander(label):
        if meta.notes:
            st.caption(meta.notes)
        if raw_set:
            st.info(
                "Configured from an imported .env value (stored raw). "
                "Saving the form below replaces it with field values.",
            )

        # How many account rows to show (each broker can hold several
        # logins; the engine joins them with commas).
        nkey = f"{meta.key}__naccts"
        n_accts = st.session_state.get(nkey, max(1, len(accounts)))
        addc, rmc = st.columns(2)
        if addc.button("Add another account", key=f"add_{meta.key}"):
            st.session_state[nkey] = n_accts + 1
            st.rerun()
        if n_accts > 1 and rmc.button(
            "Remove last account", key=f"rm_{meta.key}",
        ):
            st.session_state[nkey] = n_accts - 1
            st.rerun()

        with st.form(f"form_{meta.key}"):
            collected: list[dict[str, str]] = []
            for idx in range(n_accts):
                if n_accts > 1:
                    st.markdown(f"**Account {idx + 1}**")
                existing = accounts[idx] if idx < len(accounts) else {}
                values: dict[str, str] = {}
                for spec in meta.fields:
                    field_label = spec.label + ("" if spec.optional else " *")
                    values[spec.key] = st.text_input(
                        field_label,
                        value=existing.get(spec.key, ""),
                        type="password" if spec.secret else "default",
                        help=spec.help or None,
                        key=f"{meta.key}_{idx}_{spec.key}",
                    )
                collected.append(values)
            extra_existing = vault.get_broker_extra(meta.key)
            extra_values: dict[str, str] = {}
            for extra_var, extra_label in meta.extra_env:
                extra_values[extra_var] = st.text_input(
                    extra_label,
                    value=extra_existing.get(extra_var, ""),
                    key=f"{meta.key}_extra_{extra_var}",
                )
            if st.form_submit_button("Save"):
                nonempty = [
                    a for a in collected if any(v.strip() for v in a.values())
                ]
                totp_err = _normalize_accounts_totp(nonempty)
                if totp_err:
                    st.error(totp_err)
                elif nonempty:
                    vault.set_broker(meta.key, nonempty, extra_values)
                    st.session_state[nkey] = len(nonempty)
                    st.success(
                        f"{meta.display_name}: saved {len(nonempty)} account(s).",
                    )
                    st.rerun()
                else:
                    st.error("Nothing to save.")
        if configured:
            tcol, dcol = st.columns(2)
            if tcol.button(
                "Test login (pull balances)",
                key=f"test_{meta.key}",
                disabled=runner.is_running(),
                help="Logs into every saved account for this broker.",
            ):
                try:
                    runner.start_holdings([meta.key])
                except RunBusyError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            if dcol.button(
                f"Delete {meta.display_name} credentials", key=f"del_{meta.key}",
            ):
                vault.delete_broker(meta.key)
                st.rerun()

            # Per-account test: verify one (e.g. just-added) account's
            # login without touching the others. Field-based brokers
            # only; a raw-imported blob can't be split per account.
            if not raw_set and len(accounts) > 1:
                _render_account_tests(meta, accounts, runner)


# --------------------------------------------------------------------------
# Broker picker shared by Trade + Holdings
# --------------------------------------------------------------------------
def _broker_picker(key_prefix: str) -> list[str]:
    vault = _get_vault()
    configured = vault.configured_broker_keys()
    if not configured:
        st.warning("No brokers configured yet. Add credentials first.")
        return []
    name_by_key = {get_broker(k).display_name: k for k in configured}
    use_all = st.checkbox(
        "All configured brokers", value=True, key=f"{key_prefix}_all",
    )
    if use_all:
        return ["all"]
    chosen = st.multiselect(
        "Brokers",
        options=list(name_by_key.keys()),
        key=f"{key_prefix}_sel",
    )
    return [name_by_key[n] for n in chosen]


# --------------------------------------------------------------------------
# Trade tab
# --------------------------------------------------------------------------
def _tab_trade() -> None:  # noqa: C901, PLR0914
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Execute Trade")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return

    pending = st.session_state.get("pending_live")
    if pending:
        _render_live_confirm(runner, vault, pending)
        return

    col1, col2, col3 = st.columns(3)
    action = col1.selectbox("Action", ["buy", "sell"])
    tickers_raw = col2.text_input("Stock symbol(s)", value="", help="Comma-separated")
    amount = col3.number_input("Amount (shares)", min_value=0.0, value=1.0, step=1.0)

    col4, col5 = st.columns(2)
    price_type = col4.selectbox(
        "Order type",
        ["market", "limit"],
        help="Market is recommended. Brokers automatically fall back to a "
        "limit order (and use a limit for sub-$1 stocks) where the "
        "brokerage requires it — you don't need to force 'limit' for that.",
    )
    time_in_force = col5.selectbox(
        "Time in force",
        ["day", "gtc"],
        help="GTC (good-till-cancelled) is useful for pre/post-market "
        "limit orders. Only brokers that support it will honor it.",
    )

    limit_price: float | None = None
    if price_type == "limit":
        limit_price = st.number_input(
            "Limit price (leave blank to auto-derive)",
            min_value=0.0,
            value=None,
            step=0.01,
            format="%.2f",
            help="Exact limit price sent to the broker. Required after "
            "hours (market orders are rejected then). Leave blank to let "
            "the broker derive one from its own quote where it can "
            "(sub-$1 / extended-hours); blank does NOT work in dead "
            "overnight/weekend windows. Limit orders require exactly one "
            "symbol.",
        )

    broker_keys = _broker_picker("trade")
    dry = st.toggle(
        "Dry run (no real orders)",
        value=True,
        help="Leave ON to simulate. Turn OFF to place real trades.",
    )
    if not dry:
        st.error(
            "LIVE mode: real orders will be placed with real money.",
            icon="⚠️",
        )

    disabled = runner.is_running() or not broker_keys
    if st.button("Execute", type="primary", disabled=disabled):
        tickers, invalid = normalize_and_validate(tickers_raw)
        if invalid:
            st.error(
                "Invalid symbol(s) — fix before running so a broker login "
                f"isn't wasted: {', '.join(invalid)}",
            )
        elif not tickers:
            st.error("Enter at least one stock symbol.")
        elif price_type == "limit" and len(tickers) != 1:
            st.error(
                "Limit orders require exactly one symbol — one price "
                "can't be correct across different stocks. Use Market "
                "for multiple symbols, or run them one at a time.",
            )
        elif dry:
            try:
                runner.start_trade(
                    action,
                    float(amount),
                    tickers,
                    broker_keys,
                    dry=True,
                    price_type=price_type,
                    time_in_force=time_in_force,
                    limit_price=limit_price,
                )
            except RunBusyError as exc:
                st.error(str(exc))
            else:
                st.rerun()
        else:
            # LIVE: don't execute yet — require an explicit typed
            # confirmation showing exactly what will be sent.
            st.session_state.pending_live = {
                "action": action,
                "amount": float(amount),
                "tickers": tickers,
                "broker_keys": broker_keys,
                "price_type": price_type,
                "time_in_force": time_in_force,
                "limit_price": limit_price,
            }
            st.rerun()


def _fmt_limit(pending: dict) -> str:
    """Human-readable limit price for the LIVE confirm summary."""
    if pending["price_type"] != "limit":
        return "n/a (market)"
    lp = pending.get("limit_price")
    return f"${lp:.2f}" if lp is not None else "auto-derived by broker"


def _render_live_confirm(runner: TradeRunner, vault: Vault, pending: dict) -> None:
    """Real-money gate: show the exact order and require typing EXECUTE."""
    keys = pending["broker_keys"]
    if "all" in keys:
        names = [get_broker(k).display_name for k in vault.configured_broker_keys()]
        broker_desc = f"ALL configured: {', '.join(names)}"
    else:
        broker_desc = ", ".join(get_broker(k).display_name for k in keys)

    st.error("⚠️ Confirm LIVE order — this places REAL orders with REAL money.", icon="⚠️")
    st.markdown(
        f"- **Action:** {pending['action'].upper()}\n"
        f"- **Amount:** {pending['amount']} share(s)\n"
        f"- **Symbol(s):** {', '.join(pending['tickers'])}\n"
        f"- **Order type:** {pending['price_type']} / {pending['time_in_force']}\n"
        f"- **Limit price:** {_fmt_limit(pending)}\n"
        f"- **Brokers:** {broker_desc}\n\n"
        "This runs across **every account** at each broker above.",
    )
    typed = st.text_input("Type EXECUTE (all caps) to confirm", key="live_confirm_text")
    c1, c2 = st.columns(2)
    confirm_disabled = typed.strip() != "EXECUTE" or runner.is_running()
    if c1.button("Confirm LIVE order", type="primary", disabled=confirm_disabled):
        try:
            runner.start_trade(
                pending["action"],
                pending["amount"],
                pending["tickers"],
                pending["broker_keys"],
                dry=False,
                price_type=pending["price_type"],
                time_in_force=pending["time_in_force"],
                limit_price=pending.get("limit_price"),
            )
        except RunBusyError as exc:
            st.error(str(exc))
        else:
            st.session_state.pending_live = None
            st.rerun()
    if c2.button("Cancel"):
        st.session_state.pending_live = None
        st.rerun()


# --------------------------------------------------------------------------
# Balances and holdings tab
# --------------------------------------------------------------------------
def _tab_holdings() -> None:
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Account Balances & Holdings")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return

    broker_keys = _broker_picker("hold")
    disabled = runner.is_running() or not broker_keys
    if st.button("Pull balances / holdings", type="primary", disabled=disabled):
        try:
            runner.start_holdings(broker_keys)
        except RunBusyError as exc:
            st.error(str(exc))
        else:
            st.rerun()


# --------------------------------------------------------------------------
# Persistent activity panel: status + 2FA prompt + live log
#
# Rendered on every page (above the tabs) so a login prompt or status
# output is always visible no matter which tab triggered the run.
# --------------------------------------------------------------------------
@st.fragment(run_every=2)
def _activity_fragment(runner: TradeRunner) -> None:  # noqa: C901, PLR0912
    """Auto-refreshing activity panel (only this fragment reruns).

    Replaces the old whole-app busy-poll, so the rest of the UI stays
    responsive and the Cancel button works during a run.
    """
    snap = runner.snapshot()
    prompt = runner.prompts.snapshot()

    # One-shot in-app toast when a run reaches a terminal state.
    terminal = {RunStatus.FINISHED, RunStatus.ERROR, RunStatus.CANCELLED}
    if snap.status in terminal and st.session_state.get("_last_status") != snap.status:
        icon = {
            RunStatus.FINISHED: "✅",
            RunStatus.ERROR: "❌",
            RunStatus.CANCELLED: "⚠️",
        }[snap.status]
        st.toast(f"Run {snap.status.value}: {snap.description}", icon=icon)
    st.session_state["_last_status"] = snap.status

    status_label = {
        RunStatus.IDLE: "Idle",
        RunStatus.RUNNING: "Running…",
        RunStatus.FINISHED: "Finished",
        RunStatus.ERROR: "Error",
        RunStatus.CANCELLED: "Cancelled",
    }[snap.status]

    if snap.status == RunStatus.RUNNING and st.button(
        "⛔ Cancel run", key="cancel_run",
    ):
        runner.cancel()
        time.sleep(0.5)
        st.rerun(scope="fragment")

    # The 2FA / OTP / CAPTCHA prompt is the most urgent thing on the page.
    if prompt.waiting:
        st.error(f"🔐 Login action required: {prompt.text}", icon="🔐")
        if "captcha" in prompt.text.lower():
            captcha_path = Path("captcha.png")
            if captcha_path.is_file():
                st.image(
                    captcha_path.read_bytes(),
                    caption="Type the characters you see below.",
                )
            else:
                st.info(
                    "Waiting for the CAPTCHA image to be written "
                    f"({captcha_path.resolve()})…",
                )
        with st.form(f"prompt_{prompt.prompt_id}", clear_on_submit=True):
            answer = st.text_input(
                "Enter the code / response, then Submit",
                key=f"ans_{prompt.prompt_id}",
            )
            if st.form_submit_button("Submit", type="primary"):
                runner.prompts.respond(prompt.prompt_id, answer)
                time.sleep(0.5)
                st.rerun(scope="fragment")

    log = snap.log
    groups = group_by_broker(log) if log else {}
    if groups:
        st.markdown("**Status by broker** (verbatim lines — grouped best-effort, not interpreted)")
        for broker_name, lines in groups.items():
            with st.expander(f"{broker_name} ({len(lines)})", expanded=True):
                st.code("\n".join(lines), language="text")

    with st.expander(
        f"Activity — {status_label}",
        expanded=(snap.status != RunStatus.IDLE or prompt.waiting),
    ):
        if snap.description:
            st.caption(snap.description)
        st.download_button(
            "⬇ Download full log",
            data=log or "",
            file_name="autorsa-run.log",
            mime="text/plain",
            disabled=not log,
            key="dl_log",
        )
        # Tail very long logs so the panel stays responsive.
        max_chars = 20000
        shown = log if len(log) <= max_chars else "…(truncated — download for full log)…\n" + log[-max_chars:]
        st.code(shown or "(no output yet)", language="text")

    # Browser brokers (Wells Fargo / Fidelity / Chase) save a screenshot
    # + visible-text dump of the exact page on failure. Surface the
    # newest so the failure (esp. a 2FA chooser) is diagnosable.
    if snap.status in {RunStatus.ERROR, RunStatus.CANCELLED}:
        shots = sorted(
            Path.cwd().glob("*-error-*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if shots:
            latest = shots[0]
            st.warning(f"Failure page captured: {latest.name}")
            st.image(latest.read_bytes(), caption=latest.name)
            txt = latest.with_suffix(".txt")
            if txt.is_file():
                with st.expander("Captured page text (2FA options / buttons)"):
                    st.code(txt.read_text(encoding="utf-8", errors="replace"), language="text")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    """Render the full app."""
    _state()
    st.title("📈 AutoRSA — Local Trading GUI")
    _sidebar()

    runner = _get_runner()
    _activity_fragment(runner)

    tab_status, tab_creds, tab_trade, tab_hold = st.tabs(
        ["Status", "Credentials", "Trade", "Balances"],
    )
    with tab_status:
        _tab_status()
    with tab_creds:
        _tab_credentials()
    with tab_trade:
        _tab_trade()
    with tab_hold:
        _tab_holdings()


main()
