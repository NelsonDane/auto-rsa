"""Encrypted local credential vault.

Credentials are never written to disk in plaintext and no ``.env`` file is
generated. They are stored encrypted (Fernet, key derived from a master
password via scrypt) and only materialized into ``os.environ`` for the
duration of a single trade/holdings run, then removed again.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from src.gui.core.brokers_meta import SUPPORTED_BROKERS, get_broker

if TYPE_CHECKING:
    from collections.abc import Iterator

# Anchored at the repo root (not cwd) so the GUI finds the SAME vault
# regardless of where Streamlit was launched from. A cwd-relative path
# made the GUI offer "create new vault" when started from another dir.
VAULT_PATH = Path(__file__).resolve().parents[3] / "creds" / "vault.json"

# scrypt cost. New vaults use the stronger params; existing vault files
# store the params they were created with so they stay decryptable
# (legacy vaults predate the "kdf" field and used n=2**14).
_LEGACY_KDF = {"n": 2**14, "r": 8, "p": 1}
_STRONG_KDF = {"n": 2**16, "r": 8, "p": 1}
_KEY_LEN = 32

DEFAULT_SETTINGS: dict[str, str] = {
    "HEADLESS": "true",
    "SORT_BROKERS": "true",
    "RSA_CHASE_DIRECT_ORDER": "false",
    # Phase 7: per-signal-type allow-list. Comma-separated subset of
    # ROUND_UP_REVERSE / SPIN_OFF / SPECIAL_DIV. Default is the
    # original reverse-split flow only — no behavior change until
    # the operator explicitly enables the new types in the GUI.
    "RSA_SIGNAL_TYPES_ENABLED": "ROUND_UP_REVERSE",
}


class VaultError(Exception):
    """Raised for vault open/unlock failures."""


def _derive_key(password: str, salt: bytes, kdf: dict[str, int]) -> bytes:
    scrypt = Scrypt(
        salt=salt,
        length=_KEY_LEN,
        n=kdf["n"],
        r=kdf["r"],
        p=kdf["p"],
    )
    return base64.urlsafe_b64encode(scrypt.derive(password.encode("utf-8")))


def _empty_data() -> dict[str, Any]:
    return {"version": 2, "settings": dict(DEFAULT_SETTINGS), "brokers": {}}


class Vault:  # noqa: PLR0904
    """Encrypted on-disk store of broker credentials and GUI settings.

    The decrypted data lives only in memory after :meth:`unlock`. Call
    :meth:`materialize_env` around a run to expose credentials to the
    existing broker scripts via environment variables.
    """

    def __init__(self, path: Path = VAULT_PATH) -> None:
        """Create a vault handle for ``path`` (does not touch disk yet)."""
        self.path = path
        self._key: bytes | None = None
        self._salt: bytes | None = None
        self._kdf: dict[str, int] = dict(_STRONG_KDF)
        self._data: dict[str, Any] | None = None

    # --- lifecycle -----------------------------------------------------

    def is_initialized(self) -> bool:
        """Whether a vault file already exists on disk."""
        return self.path.exists()

    def is_unlocked(self) -> bool:
        """Whether the vault has been decrypted into memory."""
        return self._data is not None

    def initialize(self, password: str) -> None:
        """Create a brand new empty vault protected by ``password``."""
        if self.is_initialized():
            msg = "Vault already exists."
            raise VaultError(msg)
        if not password:
            msg = "Master password cannot be empty."
            raise VaultError(msg)
        self._salt = secrets.token_bytes(16)
        self._kdf = dict(_STRONG_KDF)
        self._key = _derive_key(password, self._salt, self._kdf)
        self._data = _empty_data()
        self._write()

    def unlock(self, password: str) -> None:
        """Decrypt an existing vault with ``password``."""
        if not self.is_initialized():
            msg = "No vault found. Create one first."
            raise VaultError(msg)
        try:
            blob = json.loads(self.path.read_text())
            self._salt = base64.b64decode(blob["salt"])
            token = base64.b64decode(blob["token"])
            # Legacy vaults predate the "kdf" field and used n=2**14.
            stored = blob.get("kdf")
            self._kdf = (
                {"n": int(stored["n"]), "r": int(stored["r"]), "p": int(stored["p"])}
                if isinstance(stored, dict)
                else dict(_LEGACY_KDF)
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            msg = (
                "Vault file is corrupt or unreadable. Restore a backup, or "
                "delete creds/vault.json to start over (you'll re-enter "
                "credentials)."
            )
            raise VaultError(msg) from exc
        key = _derive_key(password, self._salt, self._kdf)
        try:
            raw = Fernet(key).decrypt(token)
        except InvalidToken as exc:
            msg = "Incorrect master password."
            raise VaultError(msg) from exc
        try:
            self._data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            msg = "Vault decrypted but its contents are corrupt."
            raise VaultError(msg) from exc
        self._key = key
        self._data.setdefault("settings", dict(DEFAULT_SETTINGS))
        self._data.setdefault("brokers", {})
        self._data.setdefault("account_filter", {})
        self._data.setdefault("discovered_accounts", {})
        self._data.setdefault("sheets", {})

    def lock(self) -> None:
        """Drop decrypted data and the derived key from memory."""
        self._key = None
        self._data = None

    def change_password(self, old: str, new: str) -> None:
        """Re-encrypt the vault under a new master password."""
        self.unlock(old)
        if not new:
            msg = "New master password cannot be empty."
            raise VaultError(msg)
        # Changing the password is a natural point to upgrade a legacy
        # vault to the stronger KDF (we have the new password here).
        self._salt = secrets.token_bytes(16)
        self._kdf = dict(_STRONG_KDF)
        self._key = _derive_key(new, self._salt, self._kdf)
        self._write()

    # --- data access ---------------------------------------------------

    def _require(self) -> dict[str, Any]:
        if self._data is None:
            msg = "Vault is locked."
            raise VaultError(msg)
        return self._data

    def get_settings(self) -> dict[str, str]:
        """Return GUI/runtime settings (HEADLESS, SORT_BROKERS)."""
        return dict(self._require().get("settings", {}))

    def set_settings(self, settings: dict[str, str]) -> None:
        """Persist GUI/runtime settings."""
        self._require()["settings"] = dict(settings)
        self._write()

    def get_notify(self) -> dict[str, str]:
        """Notification config (kept out of `settings`, so never in child env)."""
        return dict(self._require().get("notify", {}))

    def set_notify(self, cfg: dict[str, str]) -> None:
        """Persist notification config (e.g. completion webhook URL)."""
        self._require()["notify"] = dict(cfg)
        self._write()

    def get_account_filter(self) -> dict[str, list[str]]:
        """Global per-broker sub-account allow-list ``{key: [mask, ...]}``.

        Empty/absent broker -> all its accounts trade (unchanged
        default). A present broker restricts buys to its listed masks;
        an explicitly empty list means trade nothing for that broker.
        Consumed by the engine via ``RSA_ACCOUNT_FILTER``.
        """
        raw = self._require().get("account_filter", {})
        return {str(k): [str(m) for m in (v or [])] for k, v in raw.items()}

    def set_account_filter(self, mapping: dict[str, list[str]]) -> None:
        """Replace the global per-broker sub-account allow-list."""
        self._require()["account_filter"] = {
            str(k): [str(m) for m in (v or [])] for k, v in mapping.items()
        }
        self._write()

    def get_discovered_accounts(self, broker_key: str) -> dict[str, list[str]]:
        """Last-4 masks seen for a broker, grouped by parent login.

        Returns ``{parent_login: [mask, ...]}`` (e.g. ``{"Fidelity 1":
        [...], "Fidelity 2": [...]}``). Legacy flat lists are surfaced
        under an empty-string parent so nothing is silently lost.
        """
        raw = self._require().get("discovered_accounts", {}).get(broker_key, {})
        if isinstance(raw, list):  # legacy flat shape
            return {"": list(raw)} if raw else {}
        return {p: list(m) for p, m in raw.items()}

    def get_discovered_masks(self, broker_key: str) -> list[str]:
        """All discovered masks for a broker, flattened (sorted, unique)."""
        groups = self.get_discovered_accounts(broker_key)
        return sorted({m for masks in groups.values() for m in masks})

    def add_discovered_accounts(
        self, broker_key: str, pairs: list[tuple[str, str]],
    ) -> None:
        """Merge newly-seen ``(parent_login, account)`` pairs.

        Accounts are stored as digit last-4 masks, grouped by the parent
        login so the Trade-tab picker can show which login each belongs
        to. Merging is per-parent (a re-run refreshes that login).
        """
        by_parent: dict[str, set[str]] = {}
        for parent, account in pairs:
            digits = re.sub(r"\D", "", str(account))
            if digits:
                by_parent.setdefault(str(parent), set()).add(digits[-4:])
        if not by_parent:
            return
        disc = self._require().setdefault("discovered_accounts", {})
        existing = disc.get(broker_key, {})
        if isinstance(existing, list):  # migrate legacy flat shape
            existing = {"": list(existing)} if existing else {}
        merged = {p: sorted(set(m)) for p, m in existing.items()}
        changed = False
        for parent, masks in by_parent.items():
            new_list = sorted(set(merged.get(parent, [])) | masks)
            if new_list != merged.get(parent):
                merged[parent] = new_list
                changed = True
        if changed:
            disc[broker_key] = merged
            self._write()

    def get_broker_accounts(self, broker_key: str) -> list[dict[str, str]]:
        """Return stored account dicts for a broker (may be empty)."""
        entry = self._require()["brokers"].get(broker_key, {})
        return [dict(a) for a in entry.get("accounts", [])]

    def get_broker_extra(self, broker_key: str) -> dict[str, str]:
        """Return broker-level extra env values (e.g. Schwab account numbers)."""
        entry = self._require()["brokers"].get(broker_key, {})
        return dict(entry.get("extra", {}))

    def set_broker(
        self,
        broker_key: str,
        accounts: list[dict[str, str]],
        extra: dict[str, str] | None = None,
    ) -> None:
        """Replace stored accounts/extra for a broker and persist.

        Refuses to add a *new* parent broker login when the active
        license tier's cap is already met (see ``src.license``).
        Updating an already-configured broker is always allowed.
        """
        from src.license import can_add_broker  # noqa: PLC0415

        get_broker(broker_key)  # validates the key
        existing = self.configured_broker_keys()
        if broker_key not in existing:
            ok, reason = can_add_broker(len(existing))
            if not ok:
                raise VaultError(reason or "License cap reached.")
        self._require()["brokers"][broker_key] = {
            "accounts": [dict(a) for a in accounts],
            "extra": dict(extra or {}),
        }
        self._write()

    def delete_broker(self, broker_key: str) -> None:
        """Remove all stored credentials for a broker."""
        self._require()["brokers"].pop(broker_key, None)
        self._write()

    def get_broker_raw(self, broker_key: str) -> str:
        """Raw env value imported from a .env (used verbatim if present)."""
        entry = self._require()["brokers"].get(broker_key, {})
        return (entry.get("raw") or "").strip()

    def configured_broker_keys(self) -> list[str]:
        """Keys of brokers that have a usable account or a raw .env value."""
        configured: list[str] = []
        for meta in SUPPORTED_BROKERS:
            if self.get_broker_raw(meta.key):
                configured.append(meta.key)
                continue
            accounts = self.get_broker_accounts(meta.key)
            if accounts and meta.assemble_env_value(accounts):
                configured.append(meta.key)
        return configured

    def get_sheets_config(self) -> dict[str, str]:
        """GUI_QUEUE Google Sheet config (service account + spreadsheet).

        Keys: ``service_account_json`` (the SA key file contents — a
        secret), ``spreadsheet_id``, ``worksheet`` (defaults GUI_QUEUE).
        """
        cfg = dict(self._require().get("sheets", {}))
        cfg.setdefault("worksheet", "GUI_QUEUE")
        return cfg

    def set_sheets_config(
        self,
        service_account_json: str,
        spreadsheet_id: str,
        worksheet: str = "GUI_QUEUE",
    ) -> None:
        """Persist the read-only GUI_QUEUE sheet config (encrypted)."""
        self._require()["sheets"] = {
            "service_account_json": service_account_json.strip(),
            "spreadsheet_id": spreadsheet_id.strip(),
            "worksheet": (worksheet or "GUI_QUEUE").strip(),
        }
        self._write()

    def secret_values(self) -> list[str]:  # noqa: C901
        """Secret strings (longest first) to redact from logs.

        Field values marked secret in brokers_meta, plus long segments of
        any raw-imported value. Length-gated to avoid redacting common
        short substrings.
        """
        out: set[str] = set()
        # Explicit secrets (FieldSpec.secret=True): redact down to 4
        # chars — a 4-char PIN or short TOTP digit run is still a
        # secret and a leak is bad. Raw .env segments use a higher
        # floor (6) because they get split on ':' / ',' and short
        # segments often match broker names, action words, etc.,
        # leading to widespread over-redaction in logs.
        min_len_secret = 4
        min_len_raw = 6
        for meta in SUPPORTED_BROKERS:
            for acc in self.get_broker_accounts(meta.key):
                for spec in meta.fields:
                    if spec.secret:
                        val = (acc.get(spec.key) or "").strip()
                        if len(val) >= min_len_secret:
                            out.add(val)
            raw = self.get_broker_raw(meta.key)
            if raw:
                for part in raw.replace(",", ":").split(":"):
                    seg = part.strip()
                    if len(seg) >= min_len_raw:
                        out.add(seg)
        sa_json = self.get_sheets_config().get("service_account_json", "")
        if sa_json:
            try:
                sa = json.loads(sa_json)
            except ValueError:
                sa = {}
            for field in ("private_key", "private_key_id", "client_email"):
                val = str(sa.get(field, "")).strip()
                if len(val) >= min_len_raw:
                    out.add(val)
        return sorted(out, key=str.__len__, reverse=True)

    def import_env_file(self, path: Path) -> dict[str, str]:
        """Import broker vars from a .env into the vault (stored as raw).

        Stored verbatim so a password containing ':' is never mangled by
        a reverse-parse. Returns {display_name: env_var} for what was
        imported. Brokers that would push the configured count past
        the active license tier's cap are skipped with a clear log
        line; existing brokers are always updated (they were already
        counted).
        """
        from dotenv import dotenv_values  # noqa: PLC0415

        from src.license import account_cap  # noqa: PLC0415

        self._require()
        if not path.is_file():
            msg = f"No .env file found at {path.resolve()}"
            raise VaultError(msg)
        values = dotenv_values(path)
        brokers = self._require()["brokers"]
        cap = account_cap()
        # Count what's already configured plus what we'll be adding.
        already_configured = set(self.configured_broker_keys())
        new_count = len(already_configured)
        imported: dict[str, str] = {}
        skipped: list[str] = []
        for meta in SUPPORTED_BROKERS:
            raw = (values.get(meta.env_var) or "").strip()
            extra = {
                ev: (values.get(ev) or "").strip()
                for ev, _label in meta.extra_env
                if (values.get(ev) or "").strip()
            }
            if not raw and not extra:
                continue
            if meta.key not in already_configured:
                if cap is not None and new_count >= cap:
                    skipped.append(meta.display_name)
                    continue
                new_count += 1
            entry = brokers.setdefault(meta.key, {})
            entry.setdefault("accounts", [])
            if raw:
                entry["raw"] = raw
                imported[meta.display_name] = meta.env_var
            if extra:
                entry["extra"] = extra
        self._write()
        if skipped:
            # Surfaced so the caller can show a single combined message
            # instead of partial-success silence.
            imported["_skipped"] = ",".join(skipped)
        return imported

    # --- persistence ---------------------------------------------------

    def _write(self) -> None:
        if self._key is None or self._salt is None or self._data is None:
            msg = "Vault not ready to write."
            raise VaultError(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = Fernet(self._key).encrypt(json.dumps(self._data).encode("utf-8"))
        payload = {
            "salt": base64.b64encode(self._salt).decode("ascii"),
            "token": base64.b64encode(token).decode("ascii"),
            "kdf": self._kdf,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(self.path)
        # Owner-only perms (best-effort; limited effect on Windows).
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)

    # --- runtime materialization --------------------------------------

    def _env_for_brokers(self, broker_keys: list[str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in broker_keys:
            meta = get_broker(key)
            raw = self.get_broker_raw(key)
            if raw:
                env[meta.env_var] = raw
            else:
                value = meta.assemble_env_value(self.get_broker_accounts(key))
                if value:
                    env[meta.env_var] = value
            for extra_var, _label in meta.extra_env:
                extra_val = (self.get_broker_extra(key).get(extra_var) or "").strip()
                if extra_val:
                    env[extra_var] = extra_val
        stored_filter = self.get_account_filter()
        active_filter = {k: stored_filter[k] for k in broker_keys if k in stored_filter}
        if active_filter:
            env["RSA_ACCOUNT_FILTER"] = json.dumps(active_filter)
        env.update(self.get_settings())
        return env

    def build_env(self, broker_keys: list[str]) -> dict[str, str]:
        """Return the env vars for the given brokers without mutating os.environ.

        Used to pass credentials to the engine subprocess via its
        environment, so nothing is written to disk and the parent
        process environment is never touched.
        """
        return self._env_for_brokers(broker_keys)

    def build_env_single_account(
        self, broker_key: str, account_index: int,
    ) -> dict[str, str]:
        """Env vars for ONE saved account of a broker (per-account test login).

        Same shape as build_env, but the broker's credential value is
        assembled from just the selected account so a test exercises
        only that account's login. Returns {} for an out-of-range
        index or a raw-imported broker (a single opaque blob can't be
        split per account).
        """
        if self.get_broker_raw(broker_key):
            return {}
        meta = get_broker(broker_key)
        accounts = self.get_broker_accounts(broker_key)
        if not 0 <= account_index < len(accounts):
            return {}
        env: dict[str, str] = {}
        value = meta.assemble_env_value([accounts[account_index]])
        if value:
            env[meta.env_var] = value
        for extra_var, _label in meta.extra_env:
            extra_val = (self.get_broker_extra(broker_key).get(extra_var) or "").strip()
            if extra_val:
                env[extra_var] = extra_val
        env.update(self.get_settings())
        return env

    @contextlib.contextmanager
    def materialize_env(self, broker_keys: list[str]) -> Iterator[None]:
        """Temporarily expose credentials/settings as environment variables.

        The variables are set on entry and reliably removed/restored on exit
        so secrets never linger in the process environment after a run.
        """
        env = self._env_for_brokers(broker_keys)
        saved: dict[str, str | None] = {}
        try:
            for name, value in env.items():
                saved[name] = os.environ.get(name)
                os.environ[name] = value
            yield
        finally:
            for name, old in saved.items():
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
