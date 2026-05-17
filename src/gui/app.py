"""Streamlit view layer for the AutoRSA GUI.

This file is intentionally thin: all state and logic live in
``src.gui.core``. It renders tabs for connection status, credential
management, trading, and balances, plus a live console that surfaces 2FA
prompts in the browser.

Run with:  uv run streamlit run src/gui/app.py
"""

from __future__ import annotations

import time

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
def _tab_trade() -> None:
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
                action, float(amount), tickers, broker_keys, dry=dry,
            )
            st.rerun()

    _render_console(runner)


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

    _render_console(runner)


# --------------------------------------------------------------------------
# Shared live console + 2FA prompt
# --------------------------------------------------------------------------
def _render_console(runner: TradeRunner) -> None:
    st.divider()
    snap = runner.snapshot()

    status_label = {
        RunStatus.IDLE: "Idle",
        RunStatus.RUNNING: "Running…",
        RunStatus.FINISHED: "Finished",
        RunStatus.ERROR: "Error",
    }[snap.status]
    st.markdown(f"**Status:** {status_label}")
    if snap.description:
        st.caption(snap.description)

    prompt = runner.prompts.snapshot()
    if prompt.waiting:
        st.warning(f"Action required: {prompt.text}")
        with st.form(f"prompt_{prompt.prompt_id}", clear_on_submit=True):
            answer = st.text_input(prompt.text, key=f"ans_{prompt.prompt_id}")
            if st.form_submit_button("Submit code / response"):
                runner.prompts.respond(prompt.prompt_id, answer)
                st.rerun()

    st.code(snap.log or "(no output yet)", language="text")

    if snap.status == RunStatus.RUNNING or prompt.waiting:
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
