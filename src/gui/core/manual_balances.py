"""Operator-entered cash balances, persisted, for the Balances view.

Two gaps this fills:
* Most brokers report only their POSITION total, not settled cash, so the
  derived ``cash = total - positions`` nets to ~0 — misleading.
* Browser brokers (Chase / Fidelity / SoFi / Wells Fargo) often can't be
  auto-pulled at all (2FA), so they never appear in the snapshot.

So the operator can record a cash figure per broker here. It's shown with
a ``*`` (manually maintained), overrides the unreliable derived cash, and
feeds the portfolio cash total. Stored at ``creds/manual_balances.json``
(gitignored with the rest of creds). Best-effort; never raises.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[3] / "creds" / "manual_balances.json"


def _isnum(v: object) -> bool:
    try:
        float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


def load() -> dict[str, float]:
    """Return ``{broker_key: cash}`` (lower-cased keys). Empty on any error."""
    with contextlib.suppress(Exception):
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                str(k).lower(): round(float(v), 2)
                for k, v in data.items()
                if _isnum(v)
            }
    return {}


def save(balances: dict[str, float]) -> None:
    """Persist ``balances``; entries that are blank / zero are dropped."""
    clean = {
        str(k).lower(): round(float(v), 2)
        for k, v in balances.items()
        if _isnum(v) and float(v) > 0
    }
    with contextlib.suppress(OSError):
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        tmp.replace(_PATH)


def get(broker_key: str) -> float | None:
    """Manually-entered cash for one broker, or None if unset."""
    return load().get(str(broker_key).lower())
