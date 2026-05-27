"""Stable per-machine hardware fingerprint.

The fingerprint is the load-bearing piece that stops one license
from being used on multiple friends' machines. It must be stable
across reboots and software updates but change on a different
machine. See ``docs/LICENSE_TIERS_DESIGN.md`` §7.

We prefer the platform's own machine identifier (IOPlatformUUID on
macOS, MachineGuid on Windows, /etc/machine-id on Linux) and then
salt+hash so the raw platform UUID is never transmitted.

A best-effort fallback returns a stable hash of the user home path
so the tool still runs on platforms where the preferred identifier
isn't readable (cap the rule, don't crash the app).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import re
import subprocess  # noqa: S404
from functools import lru_cache
from pathlib import Path

_SALT_FILE = Path(__file__).resolve().parents[2] / "creds" / "fp_salt"
_SALT_LEN = 32


def _ensure_salt() -> bytes:
    """Per-install random salt; created once, persisted, then reused.

    Stored alongside the encrypted vault. If it's ever lost the
    fingerprint changes, which is treated the same as moving to a
    new machine (operator re-bind required).
    """
    _SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _SALT_FILE.is_file():
        salt = _SALT_FILE.read_bytes()
        if len(salt) == _SALT_LEN:
            return salt
    salt = os.urandom(_SALT_LEN)
    _SALT_FILE.write_bytes(salt)
    with contextlib.suppress(OSError):
        _SALT_FILE.chmod(0o600)
    return salt


def _macos_platform_uuid() -> str | None:
    try:
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return m.group(1) if m else None


def _windows_platform_uuid() -> str | None:
    try:
        import winreg  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
            r"SOFTWARE\Microsoft\Cryptography",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")  # type: ignore[attr-defined]
            return str(value) if value else None
        finally:
            winreg.CloseKey(key)  # type: ignore[attr-defined]
    except OSError:
        return None


def _linux_platform_uuid() -> str | None:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _platform_uuid() -> str | None:
    sys = platform.system()
    if sys == "Darwin":
        return _macos_platform_uuid()
    if sys == "Windows":
        return _windows_platform_uuid()
    if sys == "Linux":
        return _linux_platform_uuid()
    return None


@lru_cache(maxsize=1)
def hardware_id() -> str:
    """Return the (cached) salted hardware fingerprint, ``h_…``."""
    raw = _platform_uuid()
    if not raw:
        # Last-resort fallback: a stable hash of the user home so
        # the rest of the app stays usable. Same machine still
        # produces the same id; different users on the same box
        # produce different ids (that's fine — they have their own
        # vaults anyway).
        raw = f"FALLBACK:{Path.home().resolve()!s}:{platform.node()}"
    salt = _ensure_salt()
    digest = hashlib.sha256(salt + raw.encode("utf-8")).hexdigest()
    return f"h_{digest[:24]}"


def reset_cache_for_tests() -> None:
    """Clear the lru_cache so tests can simulate machine changes."""
    hardware_id.cache_clear()
