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

from src.gui.core.brokers_meta import SUPPORTED_BROKERS, get_broker
from src.gui.core.runner import RunStatus, TradeRunner
from src.gui.core.vault import Vault, VaultError

st.set_page_config(page_title="AutoRSA GUI", page_icon="📈", layout="wide")

POLL_SECONDS = 2.0


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
def _sidebar() -> None:  # noqa: C901
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
    st.subheader("Credentials")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar to manage credentials.")
        return

    st.caption(
        "Credentials are encrypted at rest with your master password. "
        "No .env file is written; they are only exposed to the broker "
        "scripts in memory during a run.",
    )

    for meta in SUPPORTED_BROKERS:
        accounts = vault.get_broker_accounts(meta.key)
        existing = accounts[0] if accounts else {}
        configured = bool(accounts and meta.assemble_env_value(accounts))
        label = f"{'✅ ' if configured else ''}{meta.display_name}"
        with st.expander(label):
            if meta.notes:
                st.caption(meta.notes)
            with st.form(f"form_{meta.key}"):
                values: dict[str, str] = {}
                for spec in meta.fields:
                    field_label = spec.label + ("" if spec.optional else " *")
                    values[spec.key] = st.text_input(
                        field_label,
                        value=existing.get(spec.key, ""),
                        type="password" if spec.secret else "default",
                        help=spec.help or None,
                        key=f"{meta.key}_{spec.key}",
                    )
                extra_existing = vault.get_broker_extra(meta.key)
                extra_values: dict[str, str] = {}
                for extra_var, extra_label in meta.extra_env:
                    extra_values[extra_var] = st.text_input(
                        extra_label,
                        value=extra_existing.get(extra_var, ""),
                        key=f"{meta.key}_extra_{extra_var}",
                    )
                save = st.form_submit_button("Save")
                if save:
                    has_data = any(v.strip() for v in values.values())
                    if not has_data:
                        st.error("Nothing to save.")
                    else:
                        vault.set_broker(meta.key, [values], extra_values)
                        st.success(f"{meta.display_name} credentials saved.")
                        st.rerun()
            if configured and st.button(
                f"Delete {meta.display_name} credentials", key=f"del_{meta.key}",
            ):
                vault.delete_broker(meta.key)
                st.rerun()


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
def _tab_trade() -> None:  # noqa: PLR0914
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Execute Trade")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
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
        tickers = [t.strip() for t in tickers_raw.split(",") if t.strip()]
        if not tickers:
            st.error("Enter at least one stock symbol.")
        else:
            runner.start_trade(
                action,
                float(amount),
                tickers,
                broker_keys,
                dry=dry,
                price_type=price_type,
                time_in_force=time_in_force,
            )
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
        runner.start_holdings(broker_keys)
        st.rerun()


# --------------------------------------------------------------------------
# Persistent activity panel: status + 2FA prompt + live log
#
# Rendered on every page (above the tabs) so a login prompt or status
# output is always visible no matter which tab triggered the run.
# --------------------------------------------------------------------------
def _render_activity_panel(runner: TradeRunner) -> None:  # noqa: C901
    snap = runner.snapshot()
    prompt = runner.prompts.snapshot()

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
        st.rerun()

    # The 2FA / OTP / CAPTCHA prompt is the most urgent thing on the page.
    if prompt.waiting:
        st.error(f"🔐 Login action required: {prompt.text}", icon="🔐")
        # Some brokers (e.g. BBAE/DSPAC) save a CAPTCHA image to disk and
        # expect the characters typed back. Show it inline so the user
        # doesn't have to hunt for the file.
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
            submitted = st.form_submit_button("Submit", type="primary")
            if submitted:
                runner.prompts.respond(prompt.prompt_id, answer)
                # Give the worker a moment to consume the answer and move
                # on before we resume the auto-refresh loop.
                time.sleep(0.5)
                st.rerun()

    with st.expander(
        f"Activity — {status_label}",
        expanded=(snap.status != RunStatus.IDLE or prompt.waiting),
    ):
        if snap.description:
            st.caption(snap.description)
        st.code(snap.log or "(no output yet)", language="text")

    # Some browser brokers (e.g. Wells Fargo) save a screenshot of the
    # exact page shown when they failed. Surface the newest one on error
    # so the failure is diagnosable instead of a blind timeout.
    if snap.status == RunStatus.ERROR:
        shots = sorted(
            Path.cwd().glob("wells-fargo-error-*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if shots:
            latest = shots[0]
            st.warning("Wells Fargo failed. This is the page it was on:")
            st.image(latest.read_bytes(), caption=latest.name)

    # Stream logs by polling — but NEVER while a prompt is waiting, or the
    # rerun would wipe whatever the user is typing into the OTP box.
    if snap.status == RunStatus.RUNNING and not prompt.waiting:
        time.sleep(POLL_SECONDS)
        st.rerun()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    """Render the full app."""
    _state()
    st.title("📈 AutoRSA — Local Trading GUI")
    _sidebar()

    runner = _get_runner()
    _render_activity_panel(runner)

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
