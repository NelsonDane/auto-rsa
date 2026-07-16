"""Streamlit view layer for the AutoRSA GUI.

This file is intentionally thin: all state and logic live in
``src.gui.core``. It renders tabs for connection status, credential
management, trading, and balances, plus a live console that surfaces 2FA
prompts in the browser.

Run with:  uv run streamlit run src/gui/app.py
"""

from __future__ import annotations

import contextlib
import operator
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import streamlit as st

from src import ledger, outcomes, session_state
from src.edgar.market_calendar import parse_effective_date
from src.gui.core import (
    diagnostics,
    holdings as holdings_store,
    manual_balances,
    preflight,
    reconcile,
    watchdog,
)
from src.gui.core.brokers_meta import SUPPORTED_BROKERS, BrokerMeta, get_broker
from src.gui.core.results import group_by_broker
from src.gui.core.runner import (
    STUCK_BROKER_SECONDS,
    RunBusyError,
    RunStatus,
    TradeRunner,
)
from src.gui.core.sheets import SheetsError, Signal, fetch_signals
from src.gui.core.signal_plan import DECISION_ACTIONABLE, PlanItem, plan_signals
from src.gui.core.tickers import normalize_and_validate
from src.gui.core.totp import normalize_totp_secret
from src.gui.core.vault import Vault, VaultError

st.set_page_config(page_title="AutoRSA GUI", page_icon="📈", layout="wide")


@st.cache_data
def _build_marker() -> str:
    """Short git build id (sha + commit date) of the running code.

    Shown under the title so the operator can confirm at a glance which
    version is actually running. A stale local clone that never pulled
    the latest fix looks identical to a code bug otherwise — restarting
    Streamlit does NOT pull new code, so 'I updated GitHub but nothing
    changed' means the running checkout is behind. Best-effort; blank if
    this isn't a git checkout.
    """
    import subprocess  # noqa: PLC0415

    root = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.check_output(  # noqa: S603
            [
                "git", "-C", str(root), "show", "-s",
                "--format=%h · %cd", "--date=format:%Y-%m-%d %H:%M", "HEAD",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:  # noqa: BLE001
        return ""
    else:
        return out


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
            "🛠️ License gating is DISABLED. Toggle off below "
            "(or unset RSA_LICENSE_BYPASS) to re-enable the cap.",
        )
        _sidebar_license_bypass_toggle()
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
        _sidebar_license_bypass_toggle()


def _sidebar_license_bypass_toggle() -> None:
    """Self-hosted operator escape hatch: toggle the cap off.

    Lives in an expander labelled 'Self-hosted: disable license
    cap' so it's discoverable but not in the operator's face on a
    normal-licensed install. Creates/removes the sentinel file at
    creds/license_bypass.flag — survives across restarts; no env
    editing required.
    """
    from src.license import (  # noqa: PLC0415
        bypass_flag_path,
        set_bypass_flag,
    )

    flag_path = bypass_flag_path()
    currently_on = flag_path.is_file()
    with st.sidebar.expander("Self-hosted: disable license cap", expanded=False):
        st.caption(
            "For the self-hosted operator (you) running without an "
            "issued license token. Enabling this drops the broker "
            "cap entirely — the GUI banner will turn yellow while "
            "active. Persists across restarts via a sentinel file "
            "in creds/.",
        )
        new_state = st.checkbox(
            "Disable license broker cap",
            value=currently_on,
            key="license_bypass_toggle",
        )
        if new_state != currently_on:
            try:
                set_bypass_flag(enabled=new_state)
            except OSError as exc:
                st.error(f"Couldn't update bypass flag: {exc}")
            else:
                st.success(
                    "Bypass enabled." if new_state else "Bypass disabled.",
                )
                st.rerun()


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
        "Chase: direct order mode (recommended)",
        value=settings.get("RSA_CHASE_DIRECT_ORDER", "true") == "true",
        help="ON by default and recommended. POSTs orders directly to "
        "JPM's validate/execute endpoints via an in-page fetch, skipping "
        "the browser page navigation that HANGS Chase orders on "
        "multi-account logins. Turning this OFF falls back to the "
        "upstream path, which does not work reliably with multiple "
        "accounts.",
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
        with st.spinner("Scanning broker sessions…"):
            with contextlib.suppress(Exception):
                session_state.audit(persist=True)
        st.rerun()
    # Read the last persisted snapshot only — a full audit() on every
    # render opens creds/sessions.db under a lock (up to 30s stall if the
    # scheduled producer is mid-write) and does a per-broker ledger scan.
    # Wrap it so a lock timeout / DB error shows a friendly note instead
    # of blanking the tab with a raw traceback. First-time (no snapshot):
    # do a one-off audit, still guarded; otherwise prompt "Re-scan".
    snapshot: list[dict] = []
    try:
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
    except Exception as exc:  # noqa: BLE001
        st.warning(
            f"Could not read the session-health database ({exc}). "
            "Click 'Re-scan sessions' to retry.",
        )
        return
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
    """Pick which configured brokers a run targets.

    A single always-visible multiselect, pre-filled with every
    configured broker (so "all selected" is the default and returns
    the ``"all"`` sentinel downstream). This deliberately replaces
    the old checkbox + conditionally-revealed multiselect: that
    revealed the list only after a full-app rerun, and because a
    checkbox toggle re-executes every tab body (and races the 2s
    activity fragment), the list was slow to appear / sometimes
    didn't show. An always-present widget updates in place with no
    rerun-to-reveal.
    """
    vault = _get_vault()
    configured = vault.configured_broker_keys()
    if not configured:
        st.warning("No brokers configured yet. Add credentials first.")
        return []
    name_by_key = {get_broker(k).display_name: k for k in configured}
    all_names = list(name_by_key.keys())
    sel_key = f"{key_prefix}_sel"
    # Seed the selection ONCE via session_state instead of passing
    # `default=`. Passing BOTH default= AND writing session_state[key]
    # (the 🧹 Clear-brokers button, and Streamlit's own cross-rerun
    # persistence) trips Streamlit's "created with a default value but
    # also had its value set via the Session State API" conflict. On some
    # Streamlit/browser builds that desyncs the widget: a deselection or
    # Clear silently doesn't stick, so a broker you removed (e.g. sofi)
    # stays in the run set — its pre-flight warning persists and the run
    # targets brokers you didn't pick. Seeding through session_state and
    # dropping `default=` removes the conflict entirely.
    if sel_key not in st.session_state:
        st.session_state[sel_key] = all_names
    else:
        # Prune stored names no longer offered (a broker's creds were
        # removed). Write ONLY when something actually changed — writing a
        # widget's key on every rerun is an anti-pattern that can fight the
        # widget's own state.
        pruned = [n for n in st.session_state[sel_key] if n in all_names]
        if pruned != list(st.session_state[sel_key]):
            st.session_state[sel_key] = pruned
    chosen = st.multiselect(
        "Brokers to use",
        options=all_names,
        key=sel_key,
        help="All selected = run every configured broker. Deselect any to "
        "narrow the run. This selection is submitted WITH the Execute "
        "click, so it always matches what you see.",
    )
    if not chosen:
        st.warning("Select at least one broker to run.")
        return []
    # Everything selected -> keep the "all" sentinel so downstream
    # (confirm summary, engine env resolution) behaves exactly as the
    # old 'All configured brokers' path did.
    if set(chosen) == set(all_names):
        return ["all"]
    return [name_by_key[n] for n in chosen]


def _mask_label(mask: str) -> str:
    return f"••••{mask}"


def _account_filter_editor(  # noqa: C901
    vault: Vault, broker_keys: list[str], *, key_prefix: str = "trade",
) -> None:
    """Global per-broker sub-account allow-list editor.

    Accounts appear once a Holdings or per-account Test run has
    discovered them. Every account checked = unrestricted (trades all),
    which is the default behavior. Buys only run in checked accounts;
    sells always reach every account.

    ``key_prefix`` disambiguates the form/widget keys per caller: the
    Trade and Signals tabs both render this editor every rerun, so a
    shared key would collide (Streamlit rejects duplicate form keys).
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
        with st.form(f"{key_prefix}_acct_filter_form"):
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
                        key=f"acctfilt_{key_prefix}_{bkey}_{parent}",
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

    running = runner.is_running()
    if running:
        st.info(
            "A run is still in progress — watch / cancel it in the "
            "activity panel above, then start the next one.",
        )

    # ONE ATOMIC FORM. Every prior failure ("toggle showed OFF but read
    # ON", "typed EXECUTE but the button stayed locked") was the same
    # thing: an individual widget's update silently never reached the
    # server (the 2s activity auto-refresh can collide with in-flight
    # widget messages). A form is Streamlit's atomic primitive: NOTHING
    # syncs while the operator types, and the submit click delivers ALL
    # field values together in one message — the server acts on exactly
    # what was on screen at click time. There is no intermediate state
    # left to lose, and the order fires in the same click.
    if st.session_state.pop("_trade_arm_clear", False):
        st.session_state["trade_arm"] = ""
    # NO st.form here. st.form submissions do not reliably reach the server
    # in this deployment (plain st.button clicks DO — the sidebar Unlock
    # button, Clear, Refresh all work). A form_submit_button click was
    # handled client-side but never registered server-side, so Execute did
    # nothing. So the panel uses bare, keyed widgets (their values persist
    # in session_state and are current when a button is clicked) plus plain
    # st.button controls — the exact pattern the working Unlock uses.
    if st.button(
        "🧹 Clear brokers", key="trade_clear_brokers",
        help="Deselect all brokers so you can pick a fresh set for this trade.",
    ):
        st.session_state["trade_sel"] = []
        st.rerun()
    broker_keys = _broker_picker("trade")
    _render_preflight_warnings(broker_keys, vault)
    col1, col2, col3 = st.columns(3)
    action = col1.selectbox("Action", ["buy", "sell"], key="trade_action")
    tickers_raw = col2.text_input(
        "Stock symbol(s)", value="", help="Comma-separated",
        key="trade_tickers",
    )
    amount = col3.number_input(
        "Amount (shares)", min_value=0.0, value=1.0, step=1.0,
        key="trade_amount",
    )
    col4, col5 = st.columns(2)
    price_type = col4.selectbox(
        "Order type", ["market", "limit"], key="trade_price_type",
        help="Market is recommended. Brokers automatically fall back to a "
        "limit order (and use a limit for sub-$1 stocks) where the "
        "brokerage requires it.",
    )
    time_in_force = col5.selectbox(
        "Time in force", ["day", "gtc"], key="trade_tif",
        help="GTC (good-till-cancelled) is useful for pre/post-market "
        "limit orders. Only brokers that support it will honor it.",
    )
    limit_price_raw = st.text_input(
        "Limit price — used only for limit orders (blank = auto-derive)",
        value="", key="trade_limit_price",
        help="Exact limit price for a limit order; ignored for market "
        "orders. Limit orders require exactly one symbol.",
    )
    st.markdown(
        "**LIVE confirmation** — a LIVE run places real orders for exactly "
        "what's entered above, across **every account** at the broker(s) "
        "selected above. Dry run needs no confirmation.",
    )
    arm_text = st.text_input(
        "Type EXECUTE here to confirm a LIVE run", key="trade_arm",
    )
    c_dry, c_live = st.columns(2)
    go_dry = c_dry.button(
        "▶ Execute dry run", key="trade_go_dry",
        help="Simulate: logs in and validates, places NO real orders.",
    )
    go_live = c_live.button(
        "🔴 Execute LIVE order", key="trade_go_live", type="primary",
        help="Places REAL orders (requires EXECUTE typed above).",
    )
    _account_filter_editor(vault, broker_keys)
    _run_trade_submit(
        runner,
        go_dry=go_dry,
        go_live=go_live,
        arm_text=arm_text,
        action=action,
        amount=amount,
        tickers_raw=tickers_raw,
        broker_keys=broker_keys,
        price_type=price_type,
        time_in_force=time_in_force,
        limit_price=_parse_optional_price(limit_price_raw),
        arm_clear_flag="_trade_arm_clear",
    )


def _run_trade_submit(  # noqa: PLR0913
    runner: TradeRunner,
    *,
    go_dry: bool,
    go_live: bool,
    arm_text: str,
    action: str,
    amount: float,
    tickers_raw: str,
    broker_keys: list[str],
    price_type: str,
    time_in_force: str,
    limit_price: float | None,
    arm_clear_flag: str,
    parallel: bool = False,
    parallel_cap: int = 0,
) -> None:
    """Shared submit handler for the Trade / Trade Beta forms.

    Runs on the same script run as the form submit, with every value
    delivered atomically by the click. LIVE requires EXECUTE in
    ``arm_text`` (checked server-side); dry needs no confirmation.
    """
    if not (go_dry or go_live):
        return
    # DIAGNOSTIC breadcrumb — records exactly what this submit received and
    # where it ended up, rendered at the top of the page by
    # _render_submit_debug. This exists to END the "Execute does nothing,
    # no error" guessing: after a click, the real reason is on screen.
    dbg: dict[str, object] = {
        "tab": "beta" if parallel else "trade",
        "clicked": "LIVE" if go_live else "DRY",
        "brokers_received": list(broker_keys),
        "tickers_raw": tickers_raw,
        "arm_typed": (arm_text or "").strip(),
        "arm_ok": _execute_typed(arm_text),
        "outcome": "reached handler",
    }
    st.session_state["_submit_debug"] = dbg

    if go_live and not _execute_typed(arm_text):
        dbg["outcome"] = "BLOCKED: EXECUTE not typed in the confirm field"
        st.error(
            "LIVE order NOT started — type EXECUTE in the confirmation "
            "field, then click the red button again.",
        )
        return
    if not broker_keys:
        dbg["outcome"] = "BLOCKED: no brokers reached the server"
        st.error("Select at least one broker.")
        return
    tickers, invalid = normalize_and_validate(tickers_raw)
    if invalid:
        dbg["outcome"] = f"BLOCKED: invalid symbol(s) {invalid}"
        st.error(
            "Invalid symbol(s) — fix before running so a broker login "
            f"isn't wasted: {', '.join(invalid)}",
        )
        return
    if not tickers:
        dbg["outcome"] = "BLOCKED: no stock symbol entered"
        st.error("Enter at least one stock symbol.")
        return
    if price_type == "limit" and len(tickers) != 1:
        dbg["outcome"] = "BLOCKED: limit order needs exactly one symbol"
        st.error(
            "Limit orders require exactly one symbol — one price can't be "
            "correct across different stocks. Use Market for multiple "
            "symbols, or run them one at a time.",
        )
        return
    dbg["tickers_parsed"] = tickers
    try:
        runner.start_trade(
            action,
            float(amount),
            tickers,
            broker_keys,
            dry=not go_live,
            price_type=price_type,
            time_in_force=time_in_force,
            limit_price=limit_price,
            parallel=parallel,
            parallel_cap=parallel_cap,
        )
    except RuntimeError as exc:  # incl. RunBusyError
        dbg["outcome"] = f"BLOCKED: start_trade raised: {exc}"
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - surface ANY start failure
        dbg["outcome"] = f"BLOCKED: unexpected error: {exc!r}"
        st.error(f"Run failed to start: {exc}")
    else:
        dbg["outcome"] = "STARTED ✅"
        if go_live:
            # Disarm so the confirmation can't stay armed for a later,
            # unintended click.
            st.session_state[arm_clear_flag] = True
        # Immediate, unmistakable feedback that the click registered — the
        # activity panel shows a "run started" toast on the next render so
        # a slow cold start isn't mistaken for "Execute did nothing".
        st.session_state["_run_just_started"] = True
        st.rerun()


# --------------------------------------------------------------------------
# Trade Beta tab — same trade, but brokers run in PARALLEL (opt-in beta).
# A deliberate clone of _tab_trade so the working Trade tab is untouched.
# --------------------------------------------------------------------------
def _tab_trade_beta() -> None:  # noqa: C901, PLR0914
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Execute Trade — ⚡ Parallel (Beta)")
    st.info(
        "**Beta.** Same order as the Trade tab, but your **API brokers run "
        "at the same time** (Wells Fargo and any browser broker still run "
        "one-at-a-time for safety). The working Trade tab is unchanged. "
        "Test with a **dry run** first — this places the same REAL orders "
        "on a live run.",
        icon="⚡",
    )
    if not vault.is_unlocked():
        st.warning("Unlock the vault in the sidebar first.")
        return

    running = runner.is_running()
    if running:
        st.info(
            "A run is still in progress — watch / cancel it in the "
            "activity panel above, then start the next one.",
        )

    # NO st.form — see _tab_trade: form submissions don't reach the server
    # in this deployment; bare keyed widgets + plain st.button do.
    if st.session_state.pop("_beta_arm_clear", False):
        st.session_state["beta_arm"] = ""
    if st.button(
        "🧹 Clear brokers", key="beta_clear_brokers",
        help="Deselect all brokers so you can pick a fresh set for this trade.",
    ):
        st.session_state["beta_sel"] = []
        st.rerun()
    broker_keys = _broker_picker("beta")
    _render_preflight_warnings(broker_keys, vault)
    cap = st.slider(
        "Max brokers at once (concurrency cap)",
        min_value=1, max_value=12, value=6, key="beta_cap",
        help="How many API brokers may run simultaneously. Lower it if "
        "a broker rate-limits; 6 is a safe default.",
    )
    col1, col2, col3 = st.columns(3)
    action = col1.selectbox("Action", ["buy", "sell"], key="beta_action")
    tickers_raw = col2.text_input(
        "Stock symbol(s)", value="", help="Comma-separated",
        key="beta_tickers",
    )
    amount = col3.number_input(
        "Amount (shares)", min_value=0.0, value=1.0, step=1.0,
        key="beta_amount",
    )
    col4, col5 = st.columns(2)
    price_type = col4.selectbox(
        "Order type", ["market", "limit"], key="beta_price_type",
        help="Market is recommended; brokers fall back to a limit "
        "where required.",
    )
    time_in_force = col5.selectbox(
        "Time in force", ["day", "gtc"], key="beta_tif",
        help="GTC is useful for pre/post-market limit orders.",
    )
    limit_price_raw = st.text_input(
        "Limit price — used only for limit orders (blank = auto-derive)",
        value="", key="beta_limit_price",
        help="Exact limit price for a limit order; ignored for market "
        "orders. Limit orders require exactly one symbol.",
    )
    st.markdown(
        "**LIVE confirmation** — a LIVE parallel run places real orders "
        "for exactly what's entered above, across **every account** at the "
        "broker(s) selected above. Dry run needs no confirmation.",
    )
    arm_text = st.text_input(
        "Type EXECUTE here to confirm a LIVE run", key="beta_arm",
    )
    c_dry, c_live = st.columns(2)
    go_dry = c_dry.button(
        "▶ Execute dry run (parallel)", key="beta_go_dry",
        help="Simulate the parallel run: logs in and validates, NO real "
        "orders.",
    )
    go_live = c_live.button(
        "🔴 Execute LIVE order (parallel)", key="beta_go_live",
        type="primary",
        help="Places REAL orders (in parallel; requires EXECUTE typed).",
    )

    st.caption(
        "The per-account sub-account filter is a shared setting — edit it "
        "on the **Trade** tab; it applies here too.",
    )
    _run_trade_submit(
        runner,
        go_dry=go_dry,
        go_live=go_live,
        arm_text=arm_text,
        action=action,
        amount=amount,
        tickers_raw=tickers_raw,
        broker_keys=broker_keys,
        price_type=price_type,
        time_in_force=time_in_force,
        limit_price=_parse_optional_price(limit_price_raw),
        arm_clear_flag="_beta_arm_clear",
        parallel=True,
        parallel_cap=int(cap),
    )

    _render_parallel_summary(runner)


def _render_parallel_summary(runner: TradeRunner) -> None:
    """After a parallel run, show per-broker durations + rough time saved."""
    spec = runner.last_spec()
    if not spec or not spec.get("parallel"):
        return
    snap = runner.snapshot()
    if snap.status not in (
        RunStatus.FINISHED, RunStatus.ERROR, RunStatus.CANCELLED,
    ):
        return
    timings = [(b, s, e) for b, s, e in snap.timings]
    if not timings:
        return
    st.divider()
    st.markdown("#### Parallel run summary")
    durations = [e for _b, _s, e in timings]
    longest = max(durations) if durations else 0.0
    serial = sum(durations)
    saved = max(0.0, serial - longest)
    c1, c2, c3 = st.columns(3)
    c1.metric("Longest single broker", _fmt_elapsed(longest))
    c2.metric("Sum of all brokers", _fmt_elapsed(serial))
    c3.metric("Rough time saved", f"≤ {_fmt_elapsed(saved)}")
    st.dataframe(
        [
            {"Broker": b, "Status": s, "Duration": _fmt_elapsed(e)}
            for b, s, e in timings
        ],
        hide_index=True,
    )
    st.caption(
        "Rough estimate. Real wall-clock is between the two — API brokers "
        "run in waves of the concurrency cap and browser brokers run "
        "one-at-a-time, so it's longer than the single longest broker. "
        "Sequential would be ≈ the sum. In a parallel run the green/yellow "
        "per-broker dots in the Activity panel are approximate; each "
        "broker's ✅ ran / ❌ failed is accurate.",
    )


def _broker_display(key: str) -> str:
    """Broker display name that never raises on an unknown key."""
    try:
        return get_broker(key).display_name
    except Exception:  # noqa: BLE001
        return key


def _render_preflight_warnings(broker_keys: list[str], vault: Vault) -> None:
    """Show advisory pre-flight warnings (expired sessions, stale lock)."""
    if not broker_keys:
        return
    resolved = (
        vault.configured_broker_keys() if "all" in broker_keys else broker_keys
    )
    for w in preflight.preflight_for_run(resolved):
        st.markdown(f"- {w.icon} {w.message}")


def _fmt_elapsed(seconds: float) -> str:
    """Human-friendly elapsed time for the run timeline: '45s', '2m05s'."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:  # noqa: PLR2004
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def _execute_typed(typed: str) -> bool:
    """Whether the confirmation text clears the typed-EXECUTE gate.

    Case-insensitive on purpose: the friction that matters for the
    real-money gate is typing the whole word EXECUTE deliberately, not
    holding Shift. An operator who typed 'execute' or 'Execute' was
    being silently blocked by an exact all-caps compare with no
    feedback — a direct cause of 'I typed execute but the Confirm LIVE
    order button is not selectable'.
    """
    return typed.strip().upper() == "EXECUTE"


def _parse_optional_price(text: str) -> float | None:
    """Parse the optional limit-price text field: blank/invalid -> None
    (auto-derive), a positive number -> that price.

    Deliberately a text_input rather than a nullable ``st.number_input``.
    An empty ``st.number_input(value=None, min_value=...)`` inside a form
    can make Streamlit's frontend treat the form as invalid and SILENTLY
    refuse to submit — so a market order (which leaves this blank) could
    not be placed at all: 'Execute does nothing'. A plain text field has
    no such client-side validation gate.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


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
    running = runner.is_running()
    disabled = running or not broker_keys
    if running:
        st.info(
            "A run is in progress — watch the **Activity** panel above for "
            "live progress. If it stops on a broker asking for a login code, "
            "answer it there; if it's wedged, use the Cancel button in that "
            "panel, then try again.",
        )
    elif not broker_keys:
        st.info("Select at least one broker above.")
    if st.button("Pull balances / holdings", type="primary", disabled=disabled):
        try:
            runner.start_holdings(broker_keys)
        except RunBusyError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    st.caption(
        "Live progress streams into the **Activity** panel at the top of the "
        "page; the captured portfolio is saved and shown below. A browser "
        "broker can take a minute to log in.",
    )
    _render_holdings_dashboard(vault)


def _broker_display(bk: str) -> str:
    with contextlib.suppress(Exception):
        return get_broker(bk).display_name
    return str(bk).upper()


def _manual_cash_editor(broker_keys: list[str]) -> None:
    """Record cash per broker (persisted). Overrides the unreliable derived
    cash and covers brokers that can't be auto-pulled (browser brokers)."""
    manual = manual_balances.load()
    keys = list(dict.fromkeys([bk.lower() for bk in broker_keys] + list(manual)))
    if not keys:
        return
    with st.expander("💵 Enter cash balances manually (optional)"):
        st.caption(
            "Most brokers report only their position total, and browser "
            "brokers can't always be auto-pulled — enter each broker's cash "
            "here for an accurate total. Saved locally, shown with a **\\***, "
            "and counted in the cash total. Blank / 0 = use the auto-derived "
            "value. **Update these whenever your cash changes.**",
        )
        new: dict[str, float] = dict(manual)
        cols = st.columns(3)
        for i, bk in enumerate(sorted(keys)):
            with cols[i % 3]:
                val = st.number_input(
                    _broker_display(bk), min_value=0.0,
                    value=float(manual.get(bk, 0.0)),
                    step=1.0, format="%.2f", key=f"manual_cash_{bk}",
                )
                if val > 0:
                    new[bk] = round(val, 2)
                else:
                    new.pop(bk, None)
        b_save, b_clear = st.columns(2)
        if b_save.button("💾 Save cash balances", key="save_manual_cash"):
            manual_balances.save(new)
            st.success("Saved.")
            st.rerun()
        if manual and b_clear.button(
            "🧹 Clear all saved cash", key="clear_manual_cash",
            help="Remove every manually-entered cash figure (resets the "
            "fields to blank / auto-derived).",
        ):
            manual_balances.clear()
            # Drop the stored widget values too so the fields reset to 0.
            for k in list(st.session_state.keys()):
                if str(k).startswith("manual_cash_"):
                    del st.session_state[k]
            st.success("Cleared all saved cash.")
            st.rerun()


def _render_holdings_dashboard(vault: Vault) -> None:
    """Captured holdings: cash vs stocks up top, a section per broker
    (accounts + positions), a manual-cash editor, the brokers that weren't
    captured, and a by-ticker roll-up."""
    snap = holdings_store.load_snapshot()
    positions = snap.get("positions", [])
    by_broker = holdings_store.aggregate_by_broker(positions)
    manual = manual_balances.load()
    configured = vault.configured_broker_keys() if vault.is_unlocked() else []
    captured_keys = {b["broker"].lower() for b in by_broker}

    if not holdings_store.real_positions(positions) and not manual:
        st.divider()
        st.info(
            "No holdings captured yet. Click **Pull balances / holdings** "
            "above, or record cash manually below.",
        )
        _manual_cash_editor(configured or list(captured_keys))
        return

    st.divider()
    agg = holdings_store.aggregate_by_ticker(positions)
    stocks_total = round(sum(b["stocks_value"] for b in by_broker), 2)

    def _cash(bk: str, derived: float) -> tuple[float, bool]:
        """Effective cash + whether it's a manual figure. Manual overrides
        derived (which is ~0 for brokers that report only positions)."""
        m = manual.get(bk.lower())
        return (m, True) if m is not None else (derived, False)

    cash_total = sum(_cash(b["broker"], b["cash"])[0] for b in by_broker)
    cash_total += sum(c for bk, c in manual.items() if bk not in captured_keys)
    cash_total = round(cash_total, 2)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💵 Cash", f"${cash_total:,.2f}")
    c2.metric("📈 Stocks", f"${stocks_total:,.2f}")
    c3.metric("Total value", f"${cash_total + stocks_total:,.2f}")
    c4.metric("Distinct tickers", str(len(agg)))
    st.caption(
        "**Cash** uses your manually-entered figure where set (marked "
        "**\\***); otherwise it's derived as account total minus position "
        "value, which reads $0 for brokers that report only their positions. "
        "Enter cash below for accurate numbers.",
    )

    captured = snap.get("captured_at", {})
    if captured:
        st.caption("Captured: " + " · ".join(
            f"{b} {str(t)[:16].replace('T', ' ')}"
            for b, t in sorted(captured.items())))

    # A snapshot captured BEFORE this cash feature has no account-total
    # rows, so every broker's cash derives to $0. Detect that and prompt a
    # re-pull rather than leave the operator thinking cash is broken.
    has_account_totals = any(
        str(p.get("stock", "")).upper() == holdings_store.ACCOUNT_TOTAL_MARKER
        for p in positions
    )
    if not has_account_totals:
        st.info(
            "💡 This snapshot was captured before cash tracking, so cash "
            "shows $0. Click **Pull balances / holdings** again to capture "
            "each account's total — cash is then derived automatically "
            "(account total − position value).",
            icon="💡",
        )

    _manual_cash_editor(configured or list(captured_keys))

    st.markdown("### By broker")
    for b in by_broker:
        cash, is_manual = _cash(b["broker"], b["cash"])
        cash_str = (
            f"${cash:,.2f}{'*' if is_manual else ''}"
            if (cash > 0 or is_manual) else "—"
        )
        header = (
            f"{b['broker'].upper()} — 💵 {cash_str} cash · "
            f"📈 ${b['stocks_value']:,.2f} stocks"
        )
        with st.expander(header, expanded=len(by_broker) <= 3):  # noqa: PLR2004
            for a in b["accounts"]:
                label = a["account"] or a["parent"] or "account"
                acct_cash = f"${a['cash']:,.2f}" if a["cash"] > 0 else "—"
                st.markdown(
                    f"**{label}** — 💵 {acct_cash} cash · "
                    f"📈 ${a['stocks_value']:,.2f} stocks",
                )
                if a["holdings"]:
                    st.dataframe(
                        [
                            {
                                "Ticker": h["stock"],
                                "Shares": h["quantity"],
                                "Price": f"${h['price']:,.2f}",
                                "Value": f"${h['value']:,.2f}",
                            }
                            for h in a["holdings"]
                        ],
                        hide_index=True,
                    )
                else:
                    st.caption("No stock positions — cash only.")

    # Configured brokers that returned nothing on the last pull — surfaced
    # so they aren't silently invisible (browser brokers need 2FA; others
    # may have errored or hold nothing).
    missing = [bk for bk in configured if bk.lower() not in captured_keys]
    if missing:
        st.markdown("### Not captured on the last pull")
        st.caption(
            "Browser brokers (Chase / Fidelity / SoFi / Wells Fargo) need an "
            "interactive 2FA login; others may have errored or hold nothing. "
            "Pull again with them selected, or record cash manually above "
            "(shown with **\\***).",
        )
        st.dataframe(
            [
                {
                    "Broker": _broker_display(bk),
                    "Cash (manual)": (
                        f"${manual[bk.lower()]:,.2f}*"
                        if bk.lower() in manual else "—"
                    ),
                }
                for bk in missing
            ],
            hide_index=True,
        )

    st.markdown("### By ticker (summed across every account)")
    st.dataframe(
        [
            {
                "Ticker": r["stock"],
                "Shares": r["quantity"],
                "Value": f"${r['value']:,.2f}",
                "Brokers": r["brokers"],
            }
            for r in agg
        ],
        hide_index=True,
    )

    if st.button("Clear captured holdings", key="clear_holdings"):
        holdings_store.clear_snapshot()
        st.rerun()


def _render_reconciliation() -> None:
    """Cross-check the ledger's buys against the captured holdings."""
    st.markdown("#### Order reconciliation — did the buys actually land?")
    st.caption(
        "Cross-checks what the ledger says was bought against what the "
        "brokers actually hold. Pull holdings on the Balances tab first so "
        "the snapshot is fresh.",
    )
    snap = holdings_store.load_snapshot()
    positions = snap.get("positions", [])
    if not positions:
        st.info(
            "No holdings captured yet — pull holdings on the Balances tab, "
            "then reconcile.",
        )
        return
    try:
        rows = ledger.list_executions()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the ledger: {exc}")
        return

    findings = reconcile.reconcile(rows, positions, snap.get("captured_at", {}))
    if not findings:
        st.success("No EXECUTED / needs-review buys to reconcile.")
        return

    summary = reconcile.summarize(findings)
    missing = summary.get(reconcile.MISSING, 0)
    review_missed = summary.get(reconcile.REVIEW_MISSED, 0)
    if missing:
        st.error(
            f"🔴 {missing} order(s) reported EXECUTED but the share is NOT in "
            "the account — a possible silent failure. Verify at the broker.",
        )
    if review_missed:
        st.warning(
            f"🟠 {review_missed} ambiguous order(s) likely did NOT go "
            "through (share not held).",
        )
    if not missing and not review_missed:
        st.success("No silent failures detected in the captured brokers.")

    st.dataframe(
        [
            {
                "": f.icon,
                "Verdict": f.label,
                "Broker": f.broker,
                "Ticker": f.ticker,
                "Ledger": f.status,
                "Note": f.note,
            }
            for f in findings
        ],
        hide_index=True,
    )


# --------------------------------------------------------------------------
# Diagnostics tab: health checks, stuck-run recovery, run-log history
# --------------------------------------------------------------------------
def _tab_diagnostics() -> None:  # noqa: C901
    """Health checks, stuck-run recovery, and recent run logs."""
    vault = _get_vault()
    runner = _get_runner()
    st.subheader("Diagnostics — health & troubleshooting")

    # ---- System health -------------------------------------------------
    st.markdown("#### System health")
    st.caption(
        "Surfaces the things that make runs *silently* fail: a missing "
        "broker dependency, a stuck run lock, a full disk, a locked vault.",
    )
    deep = st.checkbox(
        "Also verify the engine imports (slower, ~10–90s) — catches a "
        "missing broker dependency that would make every run die at startup",
        value=False,
        key="diag_deep",
    )
    if st.button("Run health check", type="primary", key="diag_run"):
        checks = diagnostics.quick_health_checks(
            vault_initialized=vault.is_initialized(),
            vault_unlocked=vault.is_unlocked(),
        )
        if deep:
            with st.spinner("Importing the engine (what a run does at startup)…"):
                checks.append(diagnostics.check_engine_importable())
        st.session_state["_health_checks"] = checks
    checks = st.session_state.get("_health_checks")
    if checks:
        fails = sum(1 for c in checks if c.status == diagnostics.FAIL)
        warns = sum(1 for c in checks if c.status == diagnostics.WARN)
        if fails:
            st.error(f"{fails} check(s) FAILED — see the table below.")
        elif warns:
            st.warning(f"{warns} warning(s) — review below.")
        else:
            st.success("All checks passed.")
        st.dataframe(
            [{"": c.icon, "Check": c.name, "Detail": c.detail} for c in checks],
            hide_index=True,
        )

    st.divider()

    # ---- Stuck-run recovery -------------------------------------------
    st.markdown("#### Stuck-run recovery")
    snap = runner.snapshot()
    st.write(f"Current run status: **{snap.status.value}**")
    lock = diagnostics.inspect_run_lock()
    if lock is None:
        st.caption("No run lock is held — a new run can start.")
    elif lock["stale"]:
        st.error(
            "A run lock is held by a process that is no longer alive. This "
            "blocks every new run, and clearing it is safe.",
        )
        if st.button("🧹 Clear stuck run & release lock", key="diag_clear"):
            runner.cancel()
            released = diagnostics.force_release_run_lock()
            st.success("Cleared." if released else "Nothing to clear.")
            time.sleep(0.5)
            st.rerun()
    else:
        st.caption(
            "A run lock is held by a live process — a run is in progress "
            "(normal while running).",
        )
        if runner.is_running() and st.button(
            "⛔ Cancel the running run", key="diag_cancel",
        ):
            runner.cancel()
            time.sleep(0.5)
            st.rerun()

    st.divider()

    # ---- Render / hang diagnostics ------------------------------------
    st.markdown("#### Render / hang diagnostics")
    st.caption(
        "Every page render is traced section-by-section; if one takes "
        "longer than "
        f"{watchdog.HANG_TIMEOUT_S:.0f}s, all thread stacks are dumped to "
        "the hang log below. If the app ever freezes (clicks do nothing, "
        "content looks faded, the Stop icon stays on), the LAST line of "
        "the render trace names the section that never finished, and the "
        "hang dump names the exact stuck line of code — copy/paste both.",
    )
    trace = watchdog.read_trace()
    if trace.strip():
        completed = "RUN COMPLETE" in trace
        (st.success if completed else st.error)(
            "Last traced render: "
            + ("completed normally ✅" if completed else "NEVER FINISHED ⏱️"),
        )
        with st.expander("Render trace (this/last run)", expanded=not completed):
            st.code(trace, language="text")
    hang = watchdog.read_hang_dump()
    if hang.strip():
        st.warning(
            "A hang dump exists — a render exceeded "
            f"{watchdog.HANG_TIMEOUT_S:.0f}s at some point. The most "
            "recent stacks are at the bottom; the MainThread frame shows "
            "the exact call that was stuck.",
        )
        with st.expander("Hang dump (thread stacks)", expanded=False):
            st.code(hang, language="text")
        st.download_button(
            "⬇ Download hang dump", hang,
            file_name="gui_hang_dump.log", key="diag_hang_dl",
        )
        if st.button("Clear hang dump", key="diag_hang_clear"):
            watchdog.clear_hang_dump()
            st.rerun()
    else:
        st.caption("No hang dump — no render has exceeded the timeout.")

    st.divider()

    # ---- Order reconciliation -----------------------------------------
    _render_reconciliation()

    st.divider()

    # ---- Recent run logs ----------------------------------------------
    st.markdown("#### Recent run logs")
    st.caption(
        "Every run's full output is saved here (also where balances and "
        "order results land). Open the newest one to see what happened.",
    )
    logs = diagnostics.list_run_logs()
    if not logs:
        st.info("No run logs yet — they're written after each run.")
        return
    status_icon = {"finished": "✅", "error": "❌", "cancelled": "⚠️"}

    def _log_label(i: int) -> str:
        g = logs[i]
        when = f"{g['when']:%Y-%m-%d %H:%M UTC}" if g["when"] else g["name"]
        return f"{status_icon.get(g['status'], '•')} {when} — {g['status']}"

    idx = st.selectbox(
        "Pick a run", range(len(logs)), format_func=_log_label, key="diag_log_pick",
    )
    chosen = logs[idx]
    content = diagnostics.read_run_log(chosen["path"], tail=500)
    st.download_button(
        "⬇ Download this log", content, file_name=chosen["name"], key="diag_dl",
    )
    st.code(content, language="text")


# --------------------------------------------------------------------------
# Persistent activity panel: status + 2FA prompt + live log
#
# Rendered on every page (above the tabs) so a login prompt or status
# output is always visible no matter which tab triggered the run.
# --------------------------------------------------------------------------
def _activity_fragment(runner: TradeRunner) -> None:
    """Render the activity panel; auto-poll ONLY while something is live.

    The 2-second timer runs only while a run is active or a login prompt
    is waiting. When the app is idle there are ZERO background reruns —
    a constant idle poll can collide with in-flight widget updates in
    some browsers and silently drop them (the "toggle showed OFF but
    read ON" / "typed EXECUTE but nothing armed" class of failure), so
    the timer must not tick while the operator is composing an order.
    The interval is re-evaluated every full script run: starting a run
    is itself a full rerun (turns polling on), and any interaction after
    a run finishes turns it back off.
    """
    active = runner.is_running() or runner.prompts.snapshot().waiting
    st.fragment(_activity_fragment_body, run_every=2 if active else None)(
        runner,
    )


def _activity_fragment_body(runner: TradeRunner) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Body of the activity panel (wrapped as a fragment above).

    Once a run reaches a terminal state we render once and then
    short-circuit subsequent rerenders so the UI doesn't redraw the same
    final state every poll.
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

    # One-shot "run started" toast so clicking Execute gives unmistakable
    # feedback even before the engine's first line arrives. A cold start
    # (imports + broker login) can take 10-15s, during which the log is
    # legitimately empty — this confirms the click registered so the
    # operator doesn't assume it did nothing and re-submit (a real
    # double-order risk).
    if st.session_state.pop("_run_just_started", False):
        st.toast("🚀 Run started — watch the Activity panel here.", icon="🚀")

    # Always-available manual refresh. The 2-second auto-poll (the
    # fragment's run_every) can be unreliable on some browsers/OSes — the
    # panel can sit on "(no output yet)" while the engine is in fact
    # streaming. This button force-reruns so the operator can ALWAYS pull
    # the current status + log on demand, independent of the timer. It is
    # a deliberate click, so it never collides with in-flight widget
    # updates the way a constant idle poll would.
    if st.button("🔄 Refresh status", key="activity_refresh"):
        st.rerun()

    # NOTE: no early-return "short-circuit" here. A fragment rerun that
    # renders nothing CLEARS the fragment's previous content — an early
    # return made the whole activity panel (final status, log, download)
    # vanish 2 seconds after a run finished. Redrawing the final state is
    # cheap, and the conditional run_every above stops the polling
    # entirely on the next full rerun anyway.

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
        elapsed_by = {b: e for b, _s, e in snap.timings}
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
        # Per-broker timeline with live elapsed times (a stalled broker
        # shows a growing clock instead of a silent spinner).
        st.markdown(
            "  ".join(
                f"{pdot.get(s, '•')} {b}"
                + (
                    f" · {_fmt_elapsed(elapsed_by[b])}"
                    if b in elapsed_by and s != "pending"
                    else ""
                )
                for b, s in states.items()
            ),
        )
        # Stuck-broker hint: a broker that's been "running" too long is
        # almost always waiting on a login/2FA prompt or is hung.
        for b, s, e in snap.timings:
            if s == "running" and e >= STUCK_BROKER_SECONDS:
                st.warning(
                    f"⏱ **{b}** has been running for {_fmt_elapsed(e)} without "
                    "finishing — it's most likely waiting for a login / 2FA "
                    "code (answer it above) or is stuck. Use **⛔ Cancel run** "
                    "above if it won't progress.",
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
        if st.session_state.pop("_signal_arm_clear", False):
            st.session_state["signal_arm"] = ""
        if runner.is_running():
            st.info(
                "A run is still in progress — watch / cancel it in the "
                "activity panel above, then start the next one.",
            )
        # ONE ATOMIC FORM (same pattern as the Trade tab): the submit
        # click delivers the play, brokers and the typed EXECUTE together,
        # so nothing can be lost in flight and the run starts in that click.
        with st.form("signal_form"):
            choice = st.selectbox("Play to run", list(labels), key="signal_play")
            broker_keys = _broker_picker("signal")
            st.markdown(
                "**LIVE confirmation** — a LIVE run places a REAL 1-share "
                "buy of the selected play across the selected brokers. Dry "
                "run needs no confirmation.",
            )
            arm_text = st.text_input(
                "Type EXECUTE here to confirm a LIVE 1-share buy",
                key="signal_arm",
            )
            c_dry, c_live = st.columns(2)
            go_dry = c_dry.form_submit_button(
                "▶ Execute play (dry run)",
                help="Simulate: logs in and validates, places NO real order.",
            )
            go_live = c_live.form_submit_button(
                "🔴 Execute play LIVE (1 share)",
                type="primary",
                help="Places a REAL 1-share buy in this same click "
                "(requires EXECUTE typed above).",
            )
        _account_filter_editor(vault, broker_keys, key_prefix="signal")

        item = labels.get(choice)
        if (go_dry or go_live) and item is not None:
            if go_live and not _execute_typed(arm_text):
                st.error(
                    "LIVE buy NOT started — type EXECUTE in the confirmation "
                    "field, then click the red button again.",
                )
            elif not broker_keys:
                st.error("Select at least one broker.")
            else:
                try:
                    runner.start_signal_run(
                        ticker=item.ticker,
                        play_key=item.key,
                        split_key=item.split_key,
                        broker_keys=broker_keys,
                        dry=not go_live,
                    )
                except RuntimeError as exc:  # incl. RunBusyError
                    st.error(str(exc))
                else:
                    if go_live:
                        st.session_state["_signal_arm_clear"] = True
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
    if counts.get(ledger.STATUS_NEEDS_REVIEW):
        parts.append(f"⚠️ {counts[ledger.STATUS_NEEDS_REVIEW]} needs review")
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
    # Disable Refresh while a run is active: fetch_signals is a synchronous
    # network call on this same script thread, so if Google stalls it would
    # freeze the whole session — including an in-progress run's 2FA prompt
    # and its Cancel button. The token refresh is time-bounded (sheets.py)
    # and the fetch shows a spinner so the click isn't a black box.
    fetch_busy = _get_runner().is_running()
    if col_a.button("🔄 Refresh signals", type="primary", disabled=fetch_busy):
        try:
            with st.spinner("Fetching signals from Google Sheets…"):
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
    if fetch_busy:
        col_a.caption("Refresh is paused while a run is in progress.")

    all_signals: list[Signal] = st.session_state.get("signals", [])
    fetched_at = st.session_state.get("signals_at")
    if fetched_at is not None:
        col_b.caption(f"Last refreshed: {fetched_at:%Y-%m-%d %H:%M UTC}")
    if not all_signals:
        st.info("No signals loaded yet — click Refresh.")
        return

    # Use the NYSE/ET date, identical to plan_signals' "today". With the
    # system-local date, a host west of ET (e.g. a PT Mac Mini) disagreed
    # by a day between local and ET midnight, so a play still actionable
    # in ET could be hidden here as "past" (or a just-past one lingered).
    today = datetime.now(ZoneInfo("America/New_York")).date()
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
    # Render the ledger as ONE dataframe. The previous version created a
    # 7-column row + a Reset button for EVERY ledger row on every rerun;
    # with a large ledger that was hundreds/thousands of widgets per
    # render, taking several seconds — and because Streamlit renders every
    # tab body on every interaction, that cost was paid on EVERY click,
    # which froze the whole app (clicks queued behind a multi-second
    # render). A dataframe renders any number of rows in milliseconds.
    st.markdown(f"**{len(rows)} ledger row(s)** — newest first")
    st.dataframe(
        [
            {
                "KEY": row.get("key"),
                "Broker": row.get("broker"),
                "Account": f"••••{row.get('sub_account')}",
                "Ticker": row.get("ticker"),
                "Action": row.get("action"),
                "Status": row.get("status"),
                "Updated": str(row.get("updated_at", ""))[:19],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
    )
    # Reset ONE play via a single selectbox + button (not a per-row button).
    st.markdown("**Reset a play** so that exact play can run again")
    id_by_label = {
        f"{r.get('ticker')} {r.get('action')} · {r.get('broker')} "
        f"••••{r.get('sub_account')} · {r.get('key')}  (id {r.get('id')})":
            int(r["id"])
        for r in rows
        if r.get("id") is not None
    }
    pick = st.selectbox(
        "Pick a row to reset", ["(none)", *id_by_label],
        key="ledger_reset_pick",
    )
    if pick != "(none)" and st.button("♻ Reset selected row", key="ledger_reset_btn"):
        ledger.delete_row(id_by_label[pick])
        st.toast(f"Reset {pick}")
        st.rerun()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def _start_retry(
    runner: TradeRunner, spec: dict, brokers: list[str], *, live: bool,
) -> None:
    """Re-run ``spec`` scoped to ``brokers``. Starts the run and reruns."""
    kind = spec.get("kind")
    try:
        if kind == "holdings":
            runner.start_holdings(brokers)
        elif kind == "trade":
            runner.start_trade(
                spec["action"], spec["amount"], spec["tickers"], brokers,
                dry=not live, price_type=spec["price_type"],
                time_in_force=spec["time_in_force"],
                limit_price=spec["limit_price"],
                parallel=bool(spec.get("parallel")),
                parallel_cap=int(spec.get("parallel_cap", 0) or 0),
            )
        elif kind == "signal":
            runner.start_signal_run(
                ticker=spec["ticker"], play_key=spec["play_key"],
                split_key=spec["split_key"], broker_keys=brokers, dry=not live,
            )
        else:
            return
    except RuntimeError as exc:  # incl. RunBusyError
        st.error(str(exc))
        return
    if live:
        st.session_state["_retry_arm_clear"] = True
    st.rerun()


def _maybe_render_retry_banner(runner: TradeRunner) -> None:
    """Above the tabs: re-run only the failed brokers, in one click.

    Same same-page gate as the trade form — a LIVE re-run is confirmed by
    typing EXECUTE in an in-line form and fires on that submit; a dry /
    holdings re-run needs no confirmation. No separate screen, no queued
    session-state handoff.
    """
    snap = runner.snapshot()
    if snap.status not in (RunStatus.FINISHED, RunStatus.ERROR):
        return
    failed = [b for b, s in snap.progress if s == "failed"]
    if not failed:
        return
    spec = runner.last_spec()
    if not spec:
        return
    names = ", ".join(_broker_display(b) for b in failed)
    st.warning(f"Last run: **{len(failed)}** broker(s) failed — {names}.")

    is_live = spec.get("kind") in {"trade", "signal"} and not spec.get("dry")
    if not is_live:
        # Dry / holdings re-run — no confirmation needed.
        if st.button(
            f"🔁 Re-run the {len(failed)} failed broker(s)",
            key="retry_failed_banner",
        ):
            _start_retry(runner, spec, failed, live=False)
        return

    # LIVE re-run — same-page EXECUTE gate, delivered atomically by submit.
    if st.session_state.pop("_retry_arm_clear", False):
        st.session_state["retry_arm"] = ""
    with st.form("retry_form"):
        st.markdown(
            f"**Re-run failed brokers LIVE** — places REAL orders again on: "
            f"{names}.",
        )
        arm = st.text_input(
            "Type EXECUTE to confirm the LIVE re-run", key="retry_arm",
        )
        go = st.form_submit_button(
            f"🔁 Re-run {len(failed)} failed broker(s) LIVE", type="primary",
        )
    if go:
        if _execute_typed(arm):
            _start_retry(runner, spec, failed, live=True)
        else:
            st.error(
                "LIVE re-run NOT started — type EXECUTE, then click again.",
            )


def _kill_orphan_engine(pid: object) -> None:
    """Kill an orphaned engine process — but ONLY if it really is an
    AutoRSA engine (guards against PID reuse handing us an unrelated
    process). Best-effort; never raises.
    """
    if pid is None:
        return
    # "engine" iff the pid is alive AND its command line is the engine
    # module — the same reuse-safe check the run-lock staleness logic uses.
    if TradeRunner._engine_pid_state(pid) != "engine":  # noqa: SLF001
        return
    with contextlib.suppress(Exception):
        import psutil  # noqa: PLC0415

        psutil.Process(int(pid)).kill()


def _render_submit_debug() -> None:
    """Show what the LAST Execute/dry-run click actually did, server-side.

    Ends the 'Execute does nothing, no error' guessing: the submit handler
    records the values it received and the exact branch it took; this
    surfaces that at the top of the page so the real reason is visible.
    """
    dbg = st.session_state.get("_submit_debug")
    if not dbg:
        return
    outcome = str(dbg.get("outcome", ""))
    ok = outcome.startswith("STARTED")
    box = st.success if ok else st.warning
    box(f"🔬 Last Execute attempt → **{outcome}**")
    with st.expander("Execute diagnostic details", expanded=not ok):
        st.json(dbg)
        if st.button("Clear diagnostic", key="clear_submit_debug"):
            del st.session_state["_submit_debug"]
            st.rerun()


def _render_lock_recovery_banner(runner: TradeRunner) -> None:
    """Proactively surface a run-lock that is silently blocking new runs.

    The single-instance lock lives in ``creds/run.lock``. If a previous
    run's engine was orphaned — the GUI window was closed while a run (esp.
    a hung browser broker) was still going, so the engine subprocess kept
    running — the lock stays held, and because it lives on disk it survives
    GUI restarts. Every new Execute then raises "already in progress", but
    that error renders far down the tab where the operator never sees it:
    the exact "I click Execute and nothing happens, even after restarting"
    failure.

    Show it at the TOP of the page whenever a lock is held but THIS session
    is not running a tracked engine, with one-click recovery.
    """
    if runner.is_running():
        return  # this session owns an active run — the lock is expected
    lock = diagnostics.inspect_run_lock()
    if lock is None:
        return  # no lock held — nothing is blocking a new run
    engine_pid = lock.get("engine_pid")
    if lock["stale"]:
        st.error(
            "🔒 A leftover run-lock is blocking new runs — the process that "
            "held it is no longer alive, so clearing it is safe. Until it's "
            "cleared, clicking **Execute** does nothing.",
            icon="🔒",
        )
    else:
        st.warning(
            "🔒 A run-lock is held by another process "
            f"(engine PID {engine_pid}). New runs are blocked. If a run is "
            "active in another browser tab, let it finish. If a previous run "
            "was orphaned (its window was closed while it was still going), "
            "release the lock below to unblock trading.",
            icon="🔒",
        )
    if st.button(
        "🔓 Release run-lock and unblock trading", key="lock_recover",
        type="primary",
    ):
        # Stop an orphaned engine still holding the lock BEFORE dropping the
        # file, so a fresh run can't race a zombie into a double order.
        _kill_orphan_engine(engine_pid)
        released = diagnostics.force_release_run_lock()
        st.success(
            "Run-lock released — you can start a run now."
            if released
            else "No lock file to remove.",
        )
        time.sleep(0.4)
        st.rerun()


def main() -> None:
    """Render the full app."""
    _state()
    # Field symptom: the "Stop" indicator stays on and everything below
    # some point renders dim/stale — a script run STARTED but never
    # FINISHED, so clicks look dead and stale tab content shows (e.g.
    # Balances stuck on a pre-unlock "locked" warning while the sidebar
    # says unlocked). Which call blocks is machine-specific, so instrument
    # instead of guessing: read whether the PREVIOUS run completed, then
    # trace this run section-by-section and arm a watchdog that dumps all
    # thread stacks to creds/gui_hang_dump.log if we exceed 20s.
    prev_completed = watchdog.last_run_completed()
    prev_trace = watchdog.read_trace() if prev_completed is False else ""
    watchdog.begin_run()
    watchdog.arm()

    st.title("📈 AutoRSA — Local Trading GUI")
    _marker = _build_marker()
    if _marker:
        st.caption(f"build {_marker}")

    if prev_completed is False:
        stuck_at = ""
        lines = [ln for ln in prev_trace.strip().splitlines() if ln.strip()]
        if lines:
            stuck_at = lines[-1].split(" ", 1)[-1]
        st.error(
            "⏱️ The previous page render never finished — it stalled at "
            f"**{stuck_at or 'unknown section'}**. That freeze is why "
            "clicks seemed to do nothing and parts of the page looked "
            "faded. Open **🩺 Diagnostics → Render / hang diagnostics** "
            "and send the hang dump — it names the exact stuck line.",
            icon="⏱️",
        )

    watchdog.mark("sidebar")
    _sidebar()

    runner = _get_runner()
    watchdog.mark("activity panel")
    _activity_fragment(runner)

    # Every trade/signal path now confirms LIVE on its own page via an
    # atomic form (type EXECUTE in-form, the order fires on that submit).
    # There is no separate confirm SCREEN and no queued session-state
    # handoff — those intermittently failed to land (widget updates lost
    # to the idle auto-refresh), which repeatedly blocked live trading.
    vault = _get_vault()
    if vault.is_unlocked():
        # A held/orphaned run-lock silently blocks every new run; surface
        # it here (top of page) with one-click recovery so a stuck lock
        # can't masquerade as "Execute does nothing".
        watchdog.mark("lock/retry banners")
        _render_lock_recovery_banner(runner)
        # What the last Execute/dry click actually did, server-side.
        _render_submit_debug()
        _maybe_render_retry_banner(runner)

    (tab_status, tab_creds, tab_signals, tab_trade, tab_beta,
     tab_ledger, tab_perf, tab_hold, tab_diag) = st.tabs(
        ["Status", "Credentials", "Signals", "Trade", "⚡ Trade Beta",
         "Ledger", "Performance", "Balances", "🩺 Diagnostics"],
    )
    with tab_status:
        watchdog.mark("Status tab")
        _tab_status()
    with tab_creds:
        watchdog.mark("Credentials tab")
        _tab_credentials()
    with tab_signals:
        watchdog.mark("Signals tab")
        _tab_signals()
    with tab_trade:
        watchdog.mark("Trade tab")
        _tab_trade()
    with tab_beta:
        watchdog.mark("Trade Beta tab")
        _tab_trade_beta()
    with tab_ledger:
        watchdog.mark("Ledger tab")
        _tab_ledger()
    with tab_perf:
        watchdog.mark("Performance tab")
        _tab_performance()
    with tab_hold:
        watchdog.mark("Balances tab")
        _tab_holdings()
    with tab_diag:
        watchdog.mark("Diagnostics tab")
        _tab_diagnostics()

    watchdog.end_run()
    watchdog.disarm()


main()
