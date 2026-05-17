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
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from src.gui.core.brokers_meta import SUPPORTED_BROKERS, get_broker

if TYPE_CHECKING:
    from collections.abc import Iterator

VAULT_PATH = Path("creds") / "vault.json"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32

DEFAULT_SETTINGS: dict[str, str] = {
    "HEADLESS": "true",
    "SORT_BROKERS": "true",
}


class VaultError(Exception):
    """Raised for vault open/unlock failures."""


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _empty_data() -> dict[str, Any]:
    return {"version": 1, "settings": dict(DEFAULT_SETTINGS), "brokers": {}}


class Vault:
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
        self._key = _derive_key(password, self._salt)
        self._data = _empty_data()
        self._write()

    def unlock(self, password: str) -> None:
        """Decrypt an existing vault with ``password``."""
        if not self.is_initialized():
            msg = "No vault found. Create one first."
            raise VaultError(msg)
        blob = json.loads(self.path.read_text())
        self._salt = base64.b64decode(blob["salt"])
        token = base64.b64decode(blob["token"])
        key = _derive_key(password, self._salt)
        try:
            raw = Fernet(key).decrypt(token)
        except InvalidToken as exc:
            msg = "Incorrect master password."
            raise VaultError(msg) from exc
        self._key = key
        self._data = json.loads(raw.decode("utf-8"))
        self._data.setdefault("settings", dict(DEFAULT_SETTINGS))
        self._data.setdefault("brokers", {})

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
        self._salt = secrets.token_bytes(16)
        self._key = _derive_key(new, self._salt)
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
        """Replace stored accounts/extra for a broker and persist."""
        get_broker(broker_key)  # validates the key
        self._require()["brokers"][broker_key] = {
            "accounts": [dict(a) for a in accounts],
            "extra": dict(extra or {}),
        }
        self._write()

    def delete_broker(self, broker_key: str) -> None:
        """Remove all stored credentials for a broker."""
        self._require()["brokers"].pop(broker_key, None)
        self._write()

    def configured_broker_keys(self) -> list[str]:
        """Keys of brokers that have at least one usable account."""
        configured: list[str] = []
        for meta in SUPPORTED_BROKERS:
            accounts = self.get_broker_accounts(meta.key)
            if accounts and meta.assemble_env_value(accounts):
                configured.append(meta.key)
        return configured

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
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(self.path)

    # --- runtime materialization --------------------------------------

    def _env_for_brokers(self, broker_keys: list[str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in broker_keys:
            meta = get_broker(key)
            accounts = self.get_broker_accounts(key)
            value = meta.assemble_env_value(accounts)
            if value:
                env[meta.env_var] = value
            for extra_var, _label in meta.extra_env:
                extra_val = (self.get_broker_extra(key).get(extra_var) or "").strip()
                if extra_val:
                    env[extra_var] = extra_val
        env.update(self.get_settings())
        return env

    def build_env(self, broker_keys: list[str]) -> dict[str, str]:
        """Return the env vars for the given brokers without mutating os.environ.

        Used to pass credentials to the engine subprocess via its
        environment, so nothing is written to disk and the parent
        process environment is never touched.
        """
        return self._env_for_brokers(broker_keys)

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
