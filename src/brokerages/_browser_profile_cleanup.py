"""Free a leaked Chrome that holds a broker's persistent-profile lock.

Browser brokers (Wells Fargo, Chase) reuse a Chrome profile under
``creds/`` so a "remember this device" cookie survives between runs and
later logins skip 2FA. If a prior run's Chrome leaks — the engine was
force-killed, or the broker's close was skipped — that zombie keeps the
profile's ``SingletonLock`` held, so the NEXT run's Chrome cannot open
the same profile and the browser appears to "not open" at all.

This kills ONLY Chrome/chromedriver processes whose command line
references this broker's own profile path under ``creds/`` (never the
operator's personal Chrome), then clears the stale singleton-lock files
so Chrome reopens the SAME profile (preserving the saved session). It is
deliberately dependency-light (psutil + stdlib only, no selenium) so it
can be unit-tested. Best-effort; never raises.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def kill_stale_profile_browsers(creds_dir: str, profile_marker: str) -> int:
    """Kill leaked Chrome holding ``creds_dir``/…``profile_marker``… + clear locks.

    ``profile_marker`` is the distinctive profile-dir name segment (e.g.
    ``"wellsfargo_profile"``). Returns the number of processes killed.
    """
    killed = 0
    try:
        import psutil  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return 0
    try:
        root = Path(creds_dir).resolve()
        marker = str(root).lower()
        needle = profile_marker.lower()
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                if not ("chrome" in name or "chromedriver" in name):
                    continue
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                # Require BOTH our creds path AND this broker's profile
                # name so the operator's own Chrome is never touched.
                if marker in cmdline and needle in cmdline:
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                continue
        # Clear only the stale lock files left by the killed zombie so
        # Chrome reopens the SAME profile (keeps cookies / remembered
        # device). Never removes the profile directory itself.
        for profile in root.glob(f"*{profile_marker}*"):
            if profile.is_dir():
                for lock in _LOCK_FILES:
                    with contextlib.suppress(OSError):
                        (profile / lock).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(f"profile-browser cleanup skipped ({profile_marker}): {exc}")
    return killed
