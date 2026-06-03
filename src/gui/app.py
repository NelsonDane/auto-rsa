"""Streamlit view layer for the AutoRSA GUI.

This file is intentionally thin: all state and logic live in
``src.gui.core``. It renders tabs for connection status, credential
management, trading, and balances, plus a live console that surfaces 2FA
prompts in the browser.

Run with:  uv run streamlit run src/gui/app.py
"""

from __future__ import annotations

import operator
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import streamlit as st

from src import ledger, outcomes, session_state
from src.edgar.market_calendar import parse_effective_date
from src.gui.core.brokers_meta import SUPPORTED_BROKERS, BrokerMeta, get_broker
from src.gui.core.results import group_by_broker
from src.gui.core.runner import RunBusyError, RunStatus, TradeRunner
from src.gui.core.sheets import SheetsError, Signal, fetch_signals
from src.gui.core.signal_plan import DECISION_ACTIONABLE, PlanItem, plan_signals
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


def _sidebar_license_banner(vault: Vault) -> None:
    """Compact tier badge: shown only when vault is unlocked.

    Wrapped in try/except so an import failure inside src.license
    (e.g. cryptography missing) does not crash the whole sidebar
    and lock the operator out of unlocking the vault.
    """
    try:
        from src.license import status_summary  # noqa: PLC0415

        info = status_summary()
    except Exception as exc:
        st.sidebar.error(
            f"License module unavailable: {exc}. "
            "GUI will run as if unlicensed.",
        )
        return

    tier = info["tier"]
    badge = {
        "operator": "🟣",
        "advanced": "🟢",
        "basic": "🔵",
        "unlicensed": "⚪",
    }.get(tier, "⚪")
    configured = len(vault.configured_broker_keys()) if vault.is_unlocked() else 0
    cap_text = info["cap_text"]
    bypass_active = info.get("license_id") == "BYPASS"
    label_suffix = " (bypass)" if bypass_active else ""
    line = (
        f"{badge} **{info['tier_label']}{label_suffix}** · "
        f"{configured}/{cap_text} brokers"
    )
    st.sidebar.markdown(line)
    if bypass_active:
        # Make the bypass visible at the top of the sidebar so the
        # operator never forgets it's on. Yellow (warning) rather
        # than green so it reads as "deliberately off" not "fine".
        st.sidebar.warning(
            "🛠️ License gating is DISABLED via RSA_LICENSE_BYPASS=1. "
            "Unset that env var to re-enable the broker cap.",
        )
        return
    # Distinguish "token file unreadable" (red, action required) from
    # "no token yet" (white, just informational).
    if info.get("token_error"):
        st.sidebar.error(
            f"License token can't be read: {info['token_error']}. "
            "Re-activate or restore from backup.",
        )
    elif info["in_grace"]:
        st.sidebar.warning("License in grace window — refresh soon.")
    if tier == "unlicensed" and not info.get("token_error"):
        st.sidebar.caption(
            "Activate a license to add more brokers. Without one you "
            "can configure exactly one broker; swap it any time by "
            "deleting and adding a different one.",
        )


# --------------------------------------------------------------------------
# Sidebar: vault lock/unlock + settings
# --------------------------------------------------------------------------
def _sidebar() -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
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

    _sidebar_license_banner(vault)

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
    chase_direct = st.sidebar.checkbox(
        "Chase: direct order mode (experimental)",
        value=settings.get("RSA_CHASE_DIRECT_ORDER", "false") == "true",
        help="Skip the browser page navigation that hangs Chase orders "
        "on multi-account logins; POST directly to JPM's validate/execute "
        "endpoints using the session cookies. Holdings/login are not "
        "affected. Leave OFF until you've tested it on a single account.",
    )
    # Phase 7: per-signal-type allow-list. Operator opts into each
    # new event class individually. The Python pipeline already
    # detects them (Phase 5); these checkboxes control whether
    # plan_signals will mark them ACTIONABLE for execution.
    enabled_types_raw = settings.get(
        "RSA_SIGNAL_TYPES_ENABLED", "ROUND_UP_REVERSE",
    )
    enabled_types = {t.strip().upper() for t in enabled_types_raw.split(",") if t.strip()}
    st.sidebar.caption("**Trade signal types**")
    enable_round_up = st.sidebar.checkbox(
        "Round-up reverse splits",
        value="ROUND_UP_REVERSE" in enabled_types,
        help="The original strategy; safe default ON. Confidence floor 0.60.",
    )
    enable_spin_off = st.sidebar.checkbox(
        "Spin-offs (experimental)",
        value="SPIN_OFF" in enabled_types,
        help="Multi-broker spin-off plays. Buy parent before record date, "
        "auto-sell ~5 days after record. Confidence floor 0.75.",
    )
    enable_special_div = st.sidebar.checkbox(
        "Special dividends (experimental)",
        value="SPECIAL_DIV" in enabled_types,
        help="One-time cash distributions. Buy before record date, "
        "auto-sell ~1 day after ex-date. Confidence floor 0.75.",
    )
    new_enabled: list[str] = []
    if enable_round_up:
        new_enabled.append("ROUND_UP_REVERSE")
    if enable_spin_off:
        new_enabled.append("SPIN_OFF")
    if enable_special_div:
        new_enabled.append("SPECIAL_DIV")
    new_settings = {
        "HEADLESS": "true" if headless else "false",
        "SORT_BROKERS": "true" if sort_brokers else "false",
        "RSA_CHASE_DIRECT_ORDER": "true" if chase_direct else "false",
        "RSA_SIGNAL_TYPES_ENABLED": ",".join(new_enabled) or "ROUND_UP_REVERSE",
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

    _sidebar_backups(vault)


def _sidebar_backups(vault: Vault) -> None:  # noqa: C901, PLR0912, PLR0915
    """Sidebar Backups section: save config, back up now, restore.

    Service-account credentials come from the existing Sheets config
    (no duplicate input). Drive folder ID + passphrase are stored
    plaintext at creds/backup_config.json so the scheduled launchd
    job can run without the vault master password (same threat
    model as the unencrypted ledger).
    """
    from src.backup import (  # noqa: PLC0415
        BackupError,
        DriveError,
        backup_filename,
        list_backups,
        run_backup,
        run_restore,
    )
    from src.backup import config as bcfg  # noqa: PLC0415

    st.sidebar.divider()
    with st.sidebar.expander("🔐 Backups (Google Drive)"):
        sheets_cfg = vault.get_sheets_config()
        sa_json = sheets_cfg.get("service_account_json", "")
        if not sa_json:
            st.caption(
                "Configure the Signals tab's Google Sheet first — "
                "backups reuse the same service account.",
            )
            return

        cfg = bcfg.load()
        st.caption(
            "Encrypts vault + ledger + license token with a separate "
            "passphrase, then uploads to a Google Drive folder shared "
            "with your service account.",
        )
        folder_id = st.text_input(
            "Drive folder ID",
            value=cfg.get("drive_folder_id", ""),
            help="Create a folder in Drive, share it with the SA's "
            "client_email (Editor), paste the folder ID here.",
            key="backup_folder_id",
        )
        passphrase = st.text_input(
            "Backup passphrase",
            type="password",
            value=cfg.get("passphrase", ""),
            help="Required to decrypt the backup on restore. Keep it "
            "somewhere safe (password manager) — losing it makes the "
            "backups unreadable.",
            key="backup_passphrase",
        )
        retention = st.number_input(
            "Keep last N backups",
            min_value=1, max_value=100,
            value=int(cfg.get("retention", bcfg.DEFAULT_RETENTION)),
            help="Older backups are auto-deleted from Drive after each "
            "successful upload.",
            key="backup_retention",
        )
        if st.button("Save backup config"):
            try:
                bcfg.save(
                    drive_folder_id=folder_id.strip(),
                    passphrase=passphrase,
                    retention=int(retention),
                )
                st.success("Saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if not bcfg.is_configured():
            return

        # Manual backup
        st.divider()
        if st.button(
            f"📤 Back up now → {backup_filename()}",
            help="Creates an encrypted bundle and uploads to Drive.",
        ):
            with st.spinner("Encrypting + uploading…"):
                try:
                    summary = run_backup(sa_json=sa_json)
                except (BackupError, DriveError) as exc:
                    st.error(str(exc))
                else:
                    st.success(
                        f"Uploaded {summary['uploaded']} "
                        f"({summary['size_bytes']:,} bytes).",
                    )
                    if summary["retention_deleted"]:
                        st.caption(
                            f"Retention swept "
                            f"{len(summary['retention_deleted'])} "
                            "older backup(s).",
                        )

        # Restore
        st.divider()
        st.caption("⚠️ Restore overwrites the live vault / ledger / token. Restart the GUI after.")
        if st.button("List recent backups"):
            try:
                files = list_backups(sa_json, cfg["drive_folder_id"], max_results=20)
            except DriveError as exc:
                st.error(str(exc))
            else:
                st.session_state["_backup_listing"] = files
        files = st.session_state.get("_backup_listing", [])
        if files:
            labels = {
                f"{f.get('name', f['id'])}  ({f.get('createdTime', '')[:19].replace('T', ' ')})": f["id"]
                for f in files
            }
            pick = st.selectbox("Pick a backup", list(labels), key="backup_restore_pick")
            restore_pw = st.text_input(
                "Passphrase for this backup",
                type="password",
                key="backup_restore_pw",
            )
            confirm = st.text_input(
                "Type RESTORE to confirm",
                key="backup_restore_confirm",
            )
            if st.button(
                "♻️ Restore selected backup",
                disabled=(confirm != "RESTORE" or not restore_pw),
            ):
                with st.spinner("Downloading + decrypting…"):
                    try:
                        written = run_restore(
                            sa_json=sa_json,
                            file_id=labels[pick],
                            passphrase=restore_pw,
                        )
                    except (BackupError, DriveError) as exc:
                        st.error(str(exc))
                    else:
                        st.success(
                            f"Restored {', '.join(written)}. "
                            "Stop and restart the GUI now to "
                            "reload the on-disk state.",
                        )


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

    _broker_sessions_panel()


def _broker_sessions_panel() -> None:
    """Green/yellow/red broker session-health (read-only; no login/trade)."""
    st.markdown("#### Broker sessions")
    st.caption(
        "Health of each broker's saved login session for unattended runs. "
        "Read-only — never logs in or trades. 🔴 = needs a manual login "
        "soon; 🟡 = aging or no recent buys; 🟢 = fresh; ⚪ = no session "
        "persistence (interactive 2FA each run).",
    )
    dot = {
        session_state.GREEN: "🟢",
        session_state.YELLOW: "🟡",
        session_state.RED: "🔴",
        session_state.UNSUPPORTED: "⚪",
        session_state.UNKNOWN: "❔",
    }
    if st.button("Re-scan sessions"):
        session_state.audit(persist=True)
        st.rerun()
    snapshot = session_state.load_last_audit()
    if not snapshot:
        snapshot = [
            {
                "broker": r.broker,
                "artifact": r.artifact,
                "health": r.health,
                "reason": r.reason,
                "age_days": r.age_days,
                "last_order_at": r.last_order_at,
            }
            for r in session_state.audit(persist=True)
        ]
    # Default to only the brokers you've actually configured, so unused
    # ones (firstrade/tastytrade/tornado/tradier/vanguard/...) don't
    # clutter the panel. Toggle to see everything.
    vault = _get_vault()
    configured = (
        set(vault.configured_broker_keys()) if vault.is_unlocked() else set()
    )
    show_all = st.checkbox(
        "Show all brokers (incl. unused)", value=not configured,
    )
    rows = (
        snapshot
        if show_all or not configured
        else [r for r in snapshot if r["broker"] in configured]
    )
    reds = sum(r["health"] == session_state.RED for r in rows)
    if reds:
        st.warning(f"{reds} broker session(s) need a manual re-login.")
    st.dataframe(
        [
            {
                "": dot.get(str(r["health"]), "❔"),
                "Broker": r["broker"],
                "Artifact": r["artifact"],
                "Age (d)": r["age_days"],
                "Last buy": str(r["last_order_at"] or "—")[:19],
                "Status": r["reason"],
            }
            for r in rows
        ],
        width="stretch",
        hide_index=True,
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
                skipped = imported.pop("_skipped", "")
                if imported:
                    st.success("Imported: " + ", ".join(sorted(imported)))
                if skipped:
                    st.warning(
                        f"Skipped (license cap reached): {skipped}. "
                        "Upgrade your license to add more brokers.",
                    )
                if imported:
                    st.rerun()
                elif not skipped:
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


def _mask_label(mask: str) -> str:
    return f"••••{mask}"


def _account_filter_editor(vault: Vault, broker_keys: list[str]) -> None:  # noqa: C901
    """Global per-broker sub-account allow-list editor.

    Accounts appear once a Holdings or per-account Test run has
    discovered them. Every account checked = unrestricted (trades all),
    which is the default behavior. Buys only run in checked accounts;
    sells always reach every account.
    """
    shown = vault.configured_broker_keys() if "all" in broker_keys else broker_keys
    if not shown:
        return
    with st.expander("Sub-account filter — which accounts trade", expanded=False):
        st.caption(
            "Buys only run in the checked sub-accounts (sells always reach "
            "every account). Accounts appear here after a Holdings or Test "
            "run discovers them. All checked = trade every account (default).",
        )
        current = vault.get_account_filter()
        any_discovered = False
        with st.form("acct_filter_form"):
            pending: dict[str, list[str]] = {}
            for bkey in shown:
                groups = vault.get_discovered_accounts(bkey)
                name = get_broker(bkey).display_name
                if not groups:
                    st.markdown(
                        f"**{name}** — _no accounts discovered yet "
                        "(run Holdings or a per-account Test)_",
                    )
                    continue
                any_discovered = True
                allowed = current.get(bkey)  # None => unrestricted
                st.markdown(f"**{name}**")
                chosen_all: list[str] = []
                for parent in sorted(groups):
                    p_masks = sorted(groups[parent])
                    label = parent or name
                    default = (
                        [m for m in p_masks if m in allowed]
                        if allowed is not None
                        else p_masks
                    )
                    chosen_all += st.multiselect(
                        f"{label} ({len(p_masks)} accounts)",
                        options=p_masks,
                        default=default,
                        format_func=_mask_label,
                        key=f"acctfilt_{bkey}_{parent}",
                    )
                pending[bkey] = chosen_all
            saved = st.form_submit_button("Save sub-account filter")
        if not any_discovered:
            return
        if saved:
            new_filter = dict(vault.get_account_filter())
            warn_empty: list[str] = []
            for bkey, chosen in pending.items():
                all_masks = vault.get_discovered_masks(bkey)
                if set(chosen) == set(all_masks):
                    new_filter.pop(bkey, None)  # unrestricted
                elif chosen:
                    new_filter[bkey] = sorted(set(chosen))
                else:
                    new_filter[bkey] = []  # explicit: trade nothing
                    warn_empty.append(get_broker(bkey).display_name)
            vault.set_account_filter(new_filter)
            st.success("Sub-account filter saved.")
            if warn_empty:
                st.warning(
                    "No accounts selected for: "
                    + ", ".join(warn_empty)
                    + " — buys will be skipped entirely for these brokers.",
                )


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
    _account_filter_editor(vault, broker_keys)
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
def _activity_fragment(runner: TradeRunner) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Auto-refreshing activity panel (only this fragment reruns).

    Replaces the old whole-app busy-poll, so the rest of the UI stays
    responsive and the Cancel button works during a run.

    Polling continues for the session lifetime (Streamlit's run_every
    is a decorator-level constant), but once a run reaches a terminal
    state we render once and then short-circuit subsequent rerenders
    so the UI doesn't redraw the same final state every 2 seconds.
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

    # Already-terminal AND nothing changed since last render: skip the
    # body so the fragment stops redrawing (still polls cheaply).
    last_log_len = st.session_state.get("_last_log_len", -1)
    if (
        snap.status in terminal
        and prompt is None
        and len(snap.log) == last_log_len
    ):
        return
    st.session_state["_last_log_len"] = len(snap.log)

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

    if snap.progress:
        states = dict(snap.progress)
        total = len(states)
        finished = sum(
            1 for s in states.values()
            if s in {"done", "done_no_fill", "failed"}
        )
        running = [b for b, s in states.items() if s == "running"]
        pdot = {
            "pending": "•",
            "running": "🔄",
            "done": "✅",
            "done_no_fill": "🟡",
            "failed": "❌",
        }
        cur = f" · in progress: {', '.join(running)}" if running else ""
        st.progress(
            finished / total if total else 0.0,
            text=f"Brokers: {finished}/{total} complete{cur}",
        )
        st.markdown(
            " ".join(f"{pdot.get(s, '•')} {b}" for b, s in states.items()),
        )
        st.caption(
            "✅ at least one order placed · 🟡 broker ran clean but no "
            "orders went through (stock unavailable here?) · ❌ broker "
            "errored or timed out",
        )

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
# Signal execution (M4 — close the loop: GUI_QUEUE -> ledger -> broker)
# --------------------------------------------------------------------------
def _render_signal_live_confirm(
    runner: TradeRunner, vault: Vault, pending: dict,
) -> None:
    """Real-money gate for a signal buy — exactly 1 share, typed confirm."""
    keys = pending["broker_keys"]
    if "all" in keys:
        names = [get_broker(k).display_name for k in vault.configured_broker_keys()]
        broker_desc = f"ALL configured: {', '.join(names)}"
    else:
        broker_desc = ", ".join(get_broker(k).display_name for k in keys)

    st.error(
        "⚠️ Confirm LIVE signal buy — REAL money, exactly 1 share.",
        icon="⚠️",
    )
    st.markdown(
        f"- **Play:** {pending['ticker']} (reverse-split round-up)\n"
        f"- **Amount:** 1 share (hard-capped)\n"
        f"- **Brokers:** {broker_desc}\n"
        f"- **Sub-accounts:** only those in the saved filter; the ledger "
        f"skips any already executed for this play\n"
        f"- **KEY:** `{pending['key']}`",
    )
    typed = st.text_input(
        "Type EXECUTE (all caps) to confirm", key="signal_live_confirm_text",
    )
    c1, c2 = st.columns(2)
    disabled = typed.strip() != "EXECUTE" or runner.is_running()
    if c1.button("Confirm LIVE buy", type="primary", disabled=disabled):
        try:
            runner.start_signal_run(
                ticker=pending["ticker"],
                play_key=pending["key"],
                split_key=pending["split_key"],
                broker_keys=pending["broker_keys"],
                dry=False,
            )
        except RunBusyError as exc:
            st.error(str(exc))
        else:
            st.session_state.pending_signal_live = None
            st.rerun()
    if c2.button("Cancel"):
        st.session_state.pending_signal_live = None
        st.rerun()


def _signal_execute_section(vault: Vault, signals: list[Signal]) -> None:
    """Plan actionable signals (per-type allow-list) and run one (DRY default)."""
    runner = _get_runner()
    enabled_raw = vault.get_settings().get(
        "RSA_SIGNAL_TYPES_ENABLED", "ROUND_UP_REVERSE",
    )
    enabled = frozenset(
        t.strip().upper() for t in enabled_raw.split(",") if t.strip()
    )
    plan = plan_signals(
        signals,
        is_done=ledger.economic_done,
        enabled_signal_types=enabled,
    )
    actionable: list[PlanItem] = [
        p for p in plan if p.decision == DECISION_ACTIONABLE
    ]
    with st.expander(
        f"▶️ Execute signals — {len(actionable)} actionable "
        f"of {len(plan)}",
        expanded=False,
    ):
        st.caption(
            "Only confirmed ROUND_UP plays are runnable, exactly 1 share "
            "each. The per-account filter and the ledger (incl. "
            "cross-feed economic dedupe) still apply at execution.",
        )
        skipped = [p for p in plan if p.decision != DECISION_ACTIONABLE]
        if skipped:
            st.dataframe(
                [
                    {
                        "Ticker": p.ticker,
                        "Policy": p.fractional_policy,
                        "Conf.": p.confidence,
                        "Skipped because": p.reason,
                    }
                    for p in skipped
                ],
                width="stretch",
                hide_index=True,
            )
        if not actionable:
            st.info("No actionable ROUND_UP signals.")
            return

        labels = {
            f"{p.ticker} — {p.ratio} — {p.effective_date or '?'} "
            f"(conf {p.confidence:.2f})": p
            for p in actionable
        }
        choice = st.selectbox("Play to run", list(labels))
        item = labels[choice]
        broker_keys = _broker_picker("signal")
        _account_filter_editor(vault, broker_keys)
        dry = st.toggle(
            "Dry run (no real orders)", value=True, key="signal_dry",
            help="Leave ON to simulate. Turn OFF to place a real 1-share buy.",
        )
        if not dry:
            st.error("LIVE mode: a real 1-share order will be placed.", icon="⚠️")
        disabled = runner.is_running() or not broker_keys
        if st.button("Execute play", type="primary", disabled=disabled):
            if dry:
                try:
                    runner.start_signal_run(
                        ticker=item.ticker,
                        play_key=item.key,
                        split_key=item.split_key,
                        broker_keys=broker_keys,
                        dry=True,
                    )
                except RunBusyError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            else:
                st.session_state.pending_signal_live = {
                    "ticker": item.ticker,
                    "key": item.key,
                    "split_key": item.split_key,
                    "broker_keys": broker_keys,
                }
                st.rerun()


# --------------------------------------------------------------------------
# Signals dashboard (M2 — read-only GUI_QUEUE ingest)
# --------------------------------------------------------------------------
def _autosell_review_section(vault: Vault) -> None:  # noqa: ARG001
    """Show positions whose hold_until has passed (Phase 7/8).

    Operator-in-the-loop: each row gets a 'Sell now' button that
    routes through the existing trade runner with action=sell and the
    same dry-run gate as a manual sell. Hidden when nothing is due.

    ``vault`` is unused today but kept in the signature for symmetry
    with the other section helpers; Phase 9 will use it to look up
    the operator's per-broker filter for the sell selection.
    """
    from src.autosell import find_due_sells  # noqa: PLC0415

    runner = _get_runner()
    try:
        due = find_due_sells()
    except Exception as exc:
        st.warning(f"Auto-sell finder unavailable: {exc}")
        return
    if not due:
        return
    with st.expander(
        f"⏳ Auto-sell review — {len(due)} position(s) due",
        expanded=False,
    ):
        st.caption(
            "Positions whose hold_until is on or before today (NYSE). "
            "Click 'Sell 1' to dispatch a 1-share sell through the same "
            "trade runner you use for manual orders — dry-run gate still "
            "applies, typed-EXECUTE confirm still required for live.",
        )
        for i, d in enumerate(due):
            cols = st.columns([2, 2, 1, 2, 2, 1])
            cols[0].markdown(f"**{d.ticker}**")
            cols[1].caption(f"{d.broker}  ·  acct {d.account[-4:] if d.account else 'n/a'}")
            cols[2].caption(f"qty {d.qty:.0f}")
            cols[3].caption(d.signal_type)
            cols[4].caption(f"hold ≤ {d.hold_until}")
            disabled = runner.is_running()
            if cols[5].button(
                "Sell 1", key=f"autosell_btn_{i}",
                disabled=disabled,
            ):
                try:
                    runner.start_trade(
                        action="sell", amount=1.0, tickers=[d.ticker],
                        broker_keys=[d.broker], dry=True,
                    )
                except RunBusyError as exc:
                    st.error(str(exc))
                else:
                    st.info(
                        f"Started DRY sell of {d.ticker} on {d.broker}. "
                        "Toggle OFF Dry-run + retype EXECUTE in the Trade "
                        "tab when you're ready for live.",
                    )


def _parse_date(value: str) -> datetime | None:
    """Best-effort parse of a sheet date cell; None if unrecognizable."""
    s = (value or "").strip()
    if not s:
        return None
    iso = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(s, fmt)  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _ledger_status(key: str) -> tuple[str, dict[str, int]]:
    """Compact ledger badge + per-status counts for a signal KEY."""
    counts: dict[str, int] = {}
    for row in ledger.list_executions(key):
        st_ = str(row.get("status", ""))
        counts[st_] = counts.get(st_, 0) + 1
    if not counts:
        return "— not yet run", counts
    parts = []
    if counts.get(ledger.STATUS_EXECUTED):
        parts.append(f"✅ {counts[ledger.STATUS_EXECUTED]} done")
    if counts.get(ledger.STATUS_INTENDED):
        parts.append(f"⏳ {counts[ledger.STATUS_INTENDED]} in-flight")
    if counts.get(ledger.STATUS_FAILED):
        parts.append(f"❌ {counts[ledger.STATUS_FAILED]} failed")
    return ", ".join(parts) if parts else "—", counts


def _bucket_signals_by_day(
    signals: list[Signal],
    *,
    today: datetime | None = None,
    past_days: int = 7,
    forward_days: int = 30,
) -> tuple[list[datetime], dict[str, list[Signal]]]:
    """Return (ordered list of dates in window, signals bucketed by ISO date).

    Pure helper extracted from the calendar view so it can be unit-tested
    without Streamlit. Signals without a parseable effective date are
    excluded (they show up in the 'no parseable date' caption elsewhere).
    """
    now = today or datetime.now()  # noqa: DTZ005
    start = now.date() - timedelta(days=past_days)
    end = now.date() + timedelta(days=forward_days)
    days: list[datetime] = []
    cursor = start
    while cursor <= end:
        days.append(datetime(cursor.year, cursor.month, cursor.day))  # noqa: DTZ001
        cursor += timedelta(days=1)
    by_day: dict[str, list[Signal]] = {}
    for sig in signals:
        eff = _parse_date(sig.effective_date)
        if eff is None:
            continue
        if not (start <= eff.date() <= end):
            continue
        by_day.setdefault(eff.date().isoformat(), []).append(sig)
    return days, by_day


_DAYS_OF_WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_SUNDAY_WEEKDAY = 6


def _signal_calendar_view(signals: list[Signal]) -> None:  # noqa: C901, PLR0912, PLR0914
    """Render a 7d-back / 30d-forward calendar of upcoming signals.

    One row per ISO week, one column per weekday (Mon→Sun). Each cell
    shows the date and a count badge if signals are scheduled that day;
    today's cell is highlighted; past days render dim. Tickers for the
    day appear as a comma-separated suffix so the operator can scan
    multi-signal clusters at a glance.
    """
    days, by_day = _bucket_signals_by_day(signals)
    if not days:
        return
    today_iso = datetime.now().date().isoformat()  # noqa: DTZ005
    # Group days into ISO-weeks: list[list[datetime]] (always 7 long;
    # leading/trailing pad cells are None so weeks always align Mon-Sun).
    weeks: list[list[datetime | None]] = []
    current: list[datetime | None] = []
    # Pad the first row up to Monday.
    first = days[0]
    pad_left = first.weekday()  # Mon=0, Sun=6
    current.extend([None] * pad_left)
    for d in days:
        current.append(d)
        if d.weekday() == _SUNDAY_WEEKDAY:  # Sunday: close the week
            weeks.append(current)
            current = []
    if current:
        # Pad the last partial week to 7 cells.
        current.extend([None] * (7 - len(current)))
        weeks.append(current)
    total_in_window = sum(len(v) for v in by_day.values())
    with st.expander(
        f"📆 Open calendar — {total_in_window} signal(s) in next 30 days",
        expanded=False,
    ):
        st.caption(
            "One tile per day. The number is the count of signals with that "
            "effective date; tickers shown below. Today is highlighted; "
            "past days are dimmed. 7 days back, 30 days forward.",
        )
        # Header row: Mon-Sun
        header_cols = st.columns(7)
        for i, label in enumerate(_DAYS_OF_WEEK):
            header_cols[i].markdown(f"**{label}**")
        for week in weeks:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day is None:
                    cols[i].markdown(" ")
                    continue
                iso = day.date().isoformat()
                day_sigs = by_day.get(iso, [])
                is_today = iso == today_iso
                is_past = day.date() < datetime.now().date()  # noqa: DTZ005
                day_label = f"{day.month}/{day.day}"
                if is_today:
                    head = f"**🔵 {day_label}**"
                elif is_past:
                    head = f"_{day_label}_"
                else:
                    head = day_label
                count = len(day_sigs)
                if count:
                    badge = f"**{count} signal{'s' if count != 1 else ''}**"
                    tickers = ", ".join(sorted({s.ticker for s in day_sigs}))
                    cols[i].markdown(f"{head}\n\n{badge}\n\n_{tickers}_")
                else:
                    cols[i].markdown(head)


def _signal_rows(signals: list[Signal]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sig in signals:
        badge, _ = _ledger_status(sig.key)
        rows.append(
            {
                "Ticker": sig.ticker,
                "Ratio": sig.ratio,
                "Effective": sig.effective_date,
                "Pre-split deadline": sig.presplit_deadline,
                "Fractional": sig.fractional_policy,
                "Conf.": sig.confidence,
                "Source": sig.source,
                "Created": sig.created_at,
                "Ledger": badge,
                "KEY": sig.key,
            },
        )
    return rows


def _tab_signals() -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    vault = _get_vault()
    st.subheader("Reverse-Split Signals")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return

    pending = st.session_state.get("pending_signal_live")
    if pending:
        _render_signal_live_confirm(_get_runner(), vault, pending)
        return

    cfg = vault.get_sheets_config()
    with st.expander(
        "Google Sheet connection",
        expanded=not cfg.get("spreadsheet_id"),
    ):
        st.caption(
            "Read-only. Create a Google Cloud service account, enable the "
            "Sheets API, download its JSON key, and share the GUI_QUEUE "
            "spreadsheet with the service account's client_email (Viewer). "
            "Nothing is ever written back — accounting is local.",
        )
        sa_json = st.text_area(
            "Service-account JSON key",
            value=cfg.get("service_account_json", ""),
            height=140,
            help="Paste the full contents of the downloaded key file.",
        )
        sheet_id = st.text_input(
            "Spreadsheet ID or URL",
            value=cfg.get("spreadsheet_id", ""),
            help="The existing alert spreadsheet (GUI_QUEUE is a tab in it).",
        )
        worksheet = st.text_input(
            "Worksheet (tab) name",
            value=cfg.get("worksheet", "GUI_QUEUE"),
        )
        if st.button("Save connection"):
            vault.set_sheets_config(sa_json, sheet_id, worksheet)
            st.success("Saved.")
            st.rerun()

    cfg = vault.get_sheets_config()
    if not cfg.get("spreadsheet_id") or not cfg.get("service_account_json"):
        st.info("Configure the Google Sheet connection above to see signals.")
        return

    col_a, col_b = st.columns([1, 3])
    if col_a.button("🔄 Refresh signals", type="primary"):
        try:
            sigs = fetch_signals(
                cfg["service_account_json"],
                cfg["spreadsheet_id"],
                cfg.get("worksheet", "GUI_QUEUE"),
            )
        except SheetsError as exc:
            st.session_state.pop("signals", None)
            st.error(str(exc))
        else:
            st.session_state["signals"] = sigs
            st.session_state["signals_at"] = datetime.now(UTC)
            st.success(f"Fetched {len(sigs)} signal(s).")

    all_signals: list[Signal] = st.session_state.get("signals", [])
    fetched_at = st.session_state.get("signals_at")
    if fetched_at is not None:
        col_b.caption(f"Last refreshed: {fetched_at:%Y-%m-%d %H:%M UTC}")
    if not all_signals:
        st.info("No signals loaded yet — click Refresh.")
        return

    today = datetime.now().date()  # noqa: DTZ005
    past_signals: list[Signal] = []
    signals: list[Signal] = []
    for sig in all_signals:
        eff_d = parse_effective_date(sig.effective_date)
        if eff_d is not None and eff_d < today:
            past_signals.append(sig)
        else:
            signals.append(sig)

    _signal_execute_section(vault, signals)
    _autosell_review_section(vault)

    now = datetime.now()  # noqa: DTZ005
    week_ago = now - timedelta(days=7)
    soon = now + timedelta(days=21)

    upcoming, recent, other = [], [], []
    for sig in signals:
        eff = _parse_date(sig.effective_date) or _parse_date(
            sig.presplit_deadline,
        )
        created = _parse_date(sig.created_at)
        if eff is not None and now.date() <= eff.date() <= soon.date():
            upcoming.append((eff, sig))
        if created is not None and created >= week_ago:
            recent.append((created, sig))
        if eff is None:
            other.append(sig)

    m1, m2, m3 = st.columns(3)
    m1.metric("Signals loaded", len(signals))
    m2.metric("Upcoming (≤21d)", len(upcoming))
    m3.metric("New this week", len(recent))

    _signal_calendar_view(signals)

    st.markdown("#### 📅 Upcoming round-ups")
    if upcoming:
        upcoming.sort(key=operator.itemgetter(0))
        st.dataframe(
            _signal_rows([s for _, s in upcoming]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Nothing with a parseable effective date in the next 21 days.")

    st.markdown("#### 🆕 Alerts fired this week")
    if recent:
        recent.sort(key=operator.itemgetter(0), reverse=True)
        st.dataframe(
            _signal_rows([s for _, s in recent]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No alerts created in the last 7 days.")

    with st.expander(f"All active signals ({len(signals)})"):
        st.dataframe(
            _signal_rows(signals),
            width="stretch",
            hide_index=True,
        )
        if other:
            st.caption(
                f"{len(other)} signal(s) have no parseable effective date "
                "and are excluded from the upcoming view.",
            )

    if past_signals:
        with st.expander(
            f"Past effective date — hidden ({len(past_signals)})",
            expanded=False,
        ):
            st.caption(
                "Round date has passed; hidden from upcoming/actionable views. "
                "Ledger history for each is preserved on the Ledger tab.",
            )
            st.dataframe(
                _signal_rows(past_signals),
                width="stretch",
                hide_index=True,
            )


# --------------------------------------------------------------------------
# Ledger tab (execution history + reset a play)
# --------------------------------------------------------------------------
_AVAIL_DOT = {
    outcomes.BOUGHT: "🟢",
    outcomes.UNAVAILABLE: "🔴",
    outcomes.SESSION: "🟣",
    outcomes.REJECTED: "🟠",
    outcomes.PENDING: "🟡",
    outcomes.SKIPPED: "⚪",
}


def _play_availability_panel(rows: list[dict[str, object]]) -> None:
    """Per-play by-broker outcome matrix (read-only, from ledger reasons)."""
    matrix = outcomes.availability_matrix(rows)
    if not matrix:
        return
    brokers = sorted({b for cells in matrix.values() for b in cells})
    with st.expander(
        f"Play availability by broker ({len(matrix)} plays)", expanded=False,
    ):
        st.caption(
            "🟢 bought · 🔴 unavailable/restricted here · 🟠 rejected "
            "(market-closed/price/funds) · 🟣 session problem · 🟡 in-flight "
            "· ⚪ filtered/already-done · · none. A 🔴 means the stock "
            "wasn't buyable at that broker — not a tool failure.",
        )
        st.dataframe(
            [
                {
                    "Ticker": tkr,
                    **{
                        b: _AVAIL_DOT.get(cells.get(b, ""), "·")
                        for b in brokers
                    },
                }
                for tkr, cells in sorted(matrix.items())
            ],
            width="stretch",
            hide_index=True,
        )


def _tab_performance() -> None:
    """Per-signal-type performance dashboard (Phase 9).

    Counts are real (from the ledger). The estimated-profit column
    is `bought x operator_avg_profit_per_fill` — the operator sets
    the per-type average via the editor below. Real per-fill P&L
    would need broker-side price data the ledger doesn't capture,
    and it varies per account per day — labeled as estimate to
    keep the dashboard honest.
    """
    from src.dashboard import aggregate_by_signal_type  # noqa: PLC0415
    from src.dashboard.per_signal_type import (  # noqa: PLC0415
        DEFAULT_AVG_PROFIT_PER_FILL,
        overrides_from_settings,
        vault_setting_key,
    )

    vault = _get_vault()
    st.subheader("Performance by signal type")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return

    rows = ledger.list_executions()
    settings = vault.get_settings()
    overrides = overrides_from_settings(settings)
    metrics = aggregate_by_signal_type(rows, avg_profit_overrides=overrides)

    st.caption(
        "Counts come from the local ledger and are accurate. "
        "**Estimated profit** is `bought x avg_profit_per_fill` "
        "where `avg_profit_per_fill` is YOUR setting below — actual "
        "per-fill profit varies by broker / account / day and isn't "
        "captured by this tool. Tune the estimates after a few weeks "
        "of real fills.",
    )

    if not rows:
        st.info("No ledger activity yet — nothing to summarize.")
        return

    # Table view
    st.markdown("#### Counts + estimated profit")
    st.dataframe(
        [
            {
                "Signal type": m.signal_type,
                "Distinct alerts": m.distinct_alerts,
                "In-flight": m.intended,
                "Bought (fills)": m.bought,
                "Sold (completed)": m.sold,
                "Failed rows": m.failed,
                "Completion": f"{m.completion_rate * 100:.0f}%" if m.bought else "—",
                "Avg profit / fill": f"${m.avg_profit_per_fill_usd:.2f}",
                "Estimated profit": f"${m.estimated_profit_usd:.2f}",
            }
            for m in metrics
        ],
        width="stretch",
        hide_index=True,
    )

    # Editor for the operator estimates
    st.markdown("#### Tune avg profit per fill")
    st.caption(
        "Blank = use the code default. After a few weeks, "
        "look at actual fills and refine each per-type estimate.",
    )
    new_overrides: dict[str, str] = {}
    cols = st.columns(3)
    for i, st_type in enumerate(("ROUND_UP_REVERSE", "SPIN_OFF", "SPECIAL_DIV")):
        with cols[i]:
            default = DEFAULT_AVG_PROFIT_PER_FILL.get(st_type, 0.0)
            current = settings.get(vault_setting_key(st_type), "").strip()
            val = st.text_input(
                f"{st_type}",
                value=current,
                placeholder=f"(default ${default:.2f})",
                key=f"perf_avg_{st_type}",
                help="Dollars per filled buy. Blank to use the default.",
            )
            new_overrides[vault_setting_key(st_type)] = val.strip()
    if st.button("Save avg profit overrides"):
        merged = dict(settings)
        merged.update(new_overrides)
        vault.set_settings(merged)
        st.success("Saved. Re-render the table to see new estimates.")
        st.rerun()


def _tab_ledger() -> None:
    vault = _get_vault()
    st.subheader("Execution Ledger")
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return
    st.caption(
        "Every real (non-dry) order is recorded here so a play is never "
        "bought twice. 'Reset' clears one entry so that exact play can run "
        "again - use it to re-test, or after you've handled a stuck "
        "in-flight row by hand.",
    )

    rows = ledger.list_executions()
    if not rows:
        st.info("Ledger is empty — no real orders recorded yet.")
        return

    _play_availability_panel(rows)

    top = st.columns([1, 5])
    if top[0].button("Clear ALL", help="Wipe the entire ledger."):
        st.session_state["confirm_clear_ledger"] = True
    if st.session_state.get("confirm_clear_ledger"):
        st.warning("This permanently clears every ledger row.")
        c1, c2 = st.columns(2)
        if c1.button("Yes, clear everything", type="primary"):
            n = ledger.clear_all()
            st.session_state.pop("confirm_clear_ledger", None)
            st.success(f"Cleared {n} row(s).")
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.pop("confirm_clear_ledger", None)
            st.rerun()

    st.divider()
    hdr = st.columns([2, 1, 1, 1, 1, 2, 1])
    for col, label in zip(
        hdr,
        ["KEY", "Broker", "Account", "Ticker", "Status", "Updated", ""],
        strict=True,
    ):
        col.markdown(f"**{label}**")
    for row in rows:
        c = st.columns([2, 1, 1, 1, 1, 2, 1])
        c[0].write(row.get("key"))
        c[1].write(row.get("broker"))
        c[2].write(f"••••{row.get('sub_account')}")
        c[3].write(f"{row.get('ticker')} {row.get('action')}")
        c[4].write(row.get("status"))
        c[5].write(str(row.get("updated_at", ""))[:19])
        if c[6].button("Reset", key=f"reset_{row.get('id')}"):
            ledger.delete_row(int(row["id"]))
            st.toast(f"Reset {row.get('ticker')} / {row.get('key')}")
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
    _activity_fragment(runner)

    (tab_status, tab_creds, tab_signals, tab_trade,
     tab_ledger, tab_perf, tab_hold) = st.tabs(
        ["Status", "Credentials", "Signals", "Trade",
         "Ledger", "Performance", "Balances"],
    )
    with tab_status:
        _tab_status()
    with tab_creds:
        _tab_credentials()
    with tab_signals:
        _tab_signals()
    with tab_trade:
        _tab_trade()
    with tab_ledger:
        _tab_ledger()
    with tab_perf:
        _tab_performance()
    with tab_hold:
        _tab_holdings()


main()
