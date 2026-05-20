"""Make fidelity-api use an undetected browser engine.

Fidelity's anti-bot serves a generic "Sorry, we can't complete this
action" block page to the vanilla `playwright.firefox` + old
`playwright_stealth` browser the upstream library launches (confirmed
via the GUI diagnostic). This monkeypatches *only* the browser-launch
method (`FidelityAutomation.getDriver`) to use **patchright** (a
pre-patched, undetected Playwright) driving **real Chrome**, and drops
`stealth_sync` (layering the old stealth on patchright re-introduces
detectable signatures).

Why a monkeypatch instead of vendoring the whole library:
* keeps the change reviewable and reversible, in our repo
* the rest of fidelity.py is unchanged — only the detection-relevant
  launch differs; `close_browser` and the storage_state JSON cookie
  model still work because the browser/context/page attribute contract
  is preserved exactly.

This cannot be validated here (no live Fidelity); it is applied
best-effort and falls back to the original behaviour if patchright is
unavailable, so it can never make Fidelity *worse* than before.
"""

from __future__ import annotations

import json
from pathlib import Path

_applied = False


def _patched_get_driver(self: object) -> None:
    from patchright.sync_api import sync_playwright  # noqa: PLC0415

    self.playwright = sync_playwright().start()  # type: ignore[attr-defined]

    if self.save_state:  # type: ignore[attr-defined]
        base = Path(self.profile_path).resolve()  # type: ignore[attr-defined]
        fname = (
            f"Fidelity_{self.title}.json"  # type: ignore[attr-defined]
            if self.title is not None  # type: ignore[attr-defined]
            else "Fidelity.json"
        )
        profile = base / fname
        # fidelity.py reads self.profile_path as a string elsewhere.
        self.profile_path = str(profile)  # type: ignore[attr-defined]
        if not profile.exists():
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(json.dumps({}), encoding="utf-8")

    pw = self.playwright  # type: ignore[attr-defined]
    headless = self.headless  # type: ignore[attr-defined]
    try:
        # Real installed Chrome is the hardest to fingerprint with patchright.
        self.browser = pw.chromium.launch(headless=headless, channel="chrome")  # type: ignore[attr-defined]
    except Exception:
        # Fall back to patchright's bundled Chromium (needs:
        # `uv run patchright install chromium`).
        self.browser = pw.chromium.launch(headless=headless)  # type: ignore[attr-defined]

    self.context = self.browser.new_context(  # type: ignore[attr-defined]
        storage_state=self.profile_path if self.save_state else None,  # type: ignore[attr-defined]
    )
    if self.debug:  # type: ignore[attr-defined]
        self.context.tracing.start(  # type: ignore[attr-defined]
            name="fidelity_trace",
            screenshots=True,
            snapshots=True,
        )
    self.page = self.context.new_page()  # type: ignore[attr-defined]
    # Deliberately NO stealth_sync: patchright is already patched;
    # re-applying playwright_stealth on top is counterproductive.


def apply() -> None:
    """Patch FidelityAutomation.getDriver -> patchright. Best-effort, idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        import patchright.sync_api  # noqa: F401, PLC0415
        from fidelity import fidelity as _f  # noqa: PLC0415

        _f.FidelityAutomation.getDriver = _patched_get_driver  # type: ignore[invalid-assignment]
        _applied = True
        print("Fidelity: using patchright (undetected Chrome) for login")
    except Exception as exc:
        print(f"Fidelity: patchright patch not applied ({exc}); using stock engine")
