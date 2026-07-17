"""Apply the FRIEND build profile to a checkout's src/license/_keys.py.

Sets ``SIMPLE_MODE_DEFAULT`` and ``REQUIRE_LICENSE_TO_TRADE`` to True so
the compiled build boots into Simple Mode (Friends Edition UI) with the
license gate on. The build script runs this on a STAGED copy of the
source (never your working tree), so the flags are baked into the binary
and a friend can't flip them off.

Usage:
    python build/windows/apply_friend_profile.py <path-to-src/license/_keys.py>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_FLAGS = ("SIMPLE_MODE_DEFAULT", "REQUIRE_LICENSE_TO_TRADE")


def apply(keys_path: Path) -> list[str]:
    """Force both friend-build flags to True in ``keys_path``.

    Returns the flags whose value actually changed. Raises if a flag
    declaration can't be found (a guard against a silent no-op build).
    """
    text = keys_path.read_text(encoding="utf-8")
    changed: list[str] = []
    for name in _FLAGS:
        pat = re.compile(
            rf"^({re.escape(name)}\s*:\s*bool\s*=\s*)(?:True|False)\s*$",
            re.MULTILINE,
        )
        new, n = pat.subn(r"\g<1>True", text)
        if n == 0:
            msg = f"Could not find `{name}: bool = ...` in {keys_path}"
            raise SystemExit(msg)
        if new != text:
            changed.append(name)
        text = new
    keys_path.write_text(text, encoding="utf-8")
    return changed


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(
            "usage: apply_friend_profile.py <path-to-src/license/_keys.py>",
        )
    changed = apply(Path(argv[0]))
    print(
        "Friend profile applied. Set to True: "
        + (", ".join(changed) if changed else "(already True)"),
    )


if __name__ == "__main__":
    main(sys.argv[1:])
