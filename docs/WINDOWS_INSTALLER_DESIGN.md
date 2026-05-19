# Design: one-package Windows installer + IP protection (FOR REVIEW)

Status: **proposal, not built.** Goal: a dead-simple, self-contained
Windows installer a **non-technical trusted friend** can double-click,
that does not expose how the tool works or invite redistribution.

Context shaping this: the Discord CLI was too complicated for friends;
an earlier Discord-tied GUI existed but the tool was poorly supported
and abandoned by its original dev. So two non-negotiables here are
**install/run simplicity for non-devs** and a **reproducible,
maintainable build** (don't recreate the "great when it worked,
unsupported" failure mode).

---

## 1. Honest threat model (read first)

No client-side Python app can be made reverse-engineering-proof — the
machine must contain the logic to run it. We can only **raise the bar**:
- Stop casual inspection (the 95%): compile, strip, don't ship source.
- A determined reverse-engineer can still recover behavior.
- The *only* strong protection is **not shipping the crown jewels**
  (see §6). Everything else is deterrence + trust + a licence.

Distribution also widens the credential-risk surface, but each friend's
vault is encrypted with their **own** master password — sharing the
*tool* never exposes anyone's creds. Obfuscation ≠ security; keep them
separate in messaging to friends.

## 2. Build pipeline

- **Nuitka `--standalone`** (NOT PyInstaller). PyInstaller bundles
  `.pyc` that decompile trivially; Nuitka compiles to C/machine code —
  the meaningful anti-RE step. Prefer `--standalone` (a folder) over
  `--onefile` (onefile re-extracts to temp every launch — slow and a
  magnet for AV false-positives once a browser is bundled).
- Wrap the standalone folder in an **Inno Setup** script → a single
  signed `AutoRSA-Setup.exe` installing to `%LOCALAPPDATA%\AutoRSA`
  (per-user; no admin needed) with Start-Menu + Desktop shortcuts.
- **Reproducible build**: a `build/windows/build.ps1` + pinned deps +
  documented Nuitka flags committed to the repo, so the build is
  one command and survives a maintainer change (the lesson from the
  abandoned predecessor).

## 3. The hard part — browser binaries

The app drives patchright Chromium (Fidelity), Playwright Firefox
(Schwab), and the **system Google Chrome** (Chase/WF/Vanguard).
Options:
- **A. Bundle them** in the installer: zero first-run network, but
  ~400-600 MB installer and per-update churn.
- **B. First-run fetch** (recommended): small installer; on first
  launch a friendly progress screen runs `patchright install
  chromium` + `playwright install firefox`. Needs network once.
- **System Chrome**: detect at first run; if absent, the setup screen
  links/launches the Google Chrome installer (can't legally rebundle
  Chrome). Document clearly.

Recommend **B** with a polished first-run "Setting things up…" screen
so a non-dev never sees a terminal.

## 4. Launch & first-run UX (must be trivial)

- Double-click shortcut → compiled launcher seeds the Streamlit
  config (skip the email prompt), ensures browsers (§3), starts
  Streamlit bound to localhost, opens the default browser to the GUI.
  No Terminal, no Python, no flags — the `.cmd`/`.command` logic we
  already have, compiled and silent.
- First run: a tiny native splash ("Installing components, one
  time…") while browsers fetch; then the vault create/unlock screen.
- Per-user data in `%APPDATA%\AutoRSA` (vault, creds, ledger, logs) —
  never in the install dir, never shipped.

## 5. Anti-RE / anti-redistribution measures (deterrence stack)

1. Nuitka-compiled, **strip** `docs/`, design `.md`s, tests,
   comments/docstrings, `.git` from the shipped build.
2. **Code-sign** the installer + exe (OV cert ~$200/yr; without it
   SmartScreen/Defender throw scary warnings at non-tech friends and
   may quarantine — signing is near-mandatory for this audience).
3. Optional **licence-key gate**: a per-friend key checked at startup
   (offline-verifiable signature). Deters casual sharing; not RE.
4. A short **licence/use agreement** at install ("personal use, no
   redistribution or decompilation"). Technical + legal together.
5. Optional remote **kill switch / version check** (a signed JSON the
   app fetches) so an abused/old build can be disabled — only if you
   want that control; adds a network dependency.

## 6. The strong option — don't ship the crown jewels

The real IP is the **EDGAR classifier + Apps Script signal pipeline**,
not the GUI/executor. The architecture already separates them: the GUI
consumes `GUI_QUEUE`. So:
- Friends get an installer that runs **only the GUI + executor**, and
  consume a `GUI_QUEUE` sheet **you** populate centrally (your Mac
  Mini producer).
- The classifier never lands on their machines → it cannot be RE'd at
  all, regardless of how good their tools are.
- Bonus: you control signal quality/rollout for the whole group.

For "a few trusted friends" shipping the compiled scraper too is
acceptable; if the circle grows, the central-sheet model is the
defensible line. **Recommended: design the installer so the scraper is
an optional, separately-gated component, default OFF for friend
builds.**

## 7. Maintainability (so this doesn't get abandoned too)

- Pinned deps + `.python-version` (already done) + committed build
  script = anyone can rebuild.
- Versioned releases; an in-app "A new version is available" notice
  (re-run the installer to update — no fragile auto-update v1).
- A short BUILD.md runbook (mirrors the Mac Mini guide style).
- Every Playwright/dep bump = re-test the frozen build (known fragile
  point; call it out in the runbook).

## 8. Phased plan (when approved)

1. **Reproducible Nuitka standalone** that launches the GUI on a clean
   Windows VM (no Python installed) — proves the freeze handles
   Streamlit + dynamic imports.
2. **Browser strategy** (§3B) with the first-run setup screen.
3. **Inno Setup installer + code signing** → `AutoRSA-Setup.exe`.
4. **Strip + licence file + (optional) key gate**.
5. **Friend-build profile**: scraper component OFF, consumes central
   `GUI_QUEUE` (§6).

## 9. Open decisions for review

1. Bundle browsers (A) vs first-run fetch (B, recommended)?
2. Ship the compiled scraper to friends, or central-sheet model
   (recommended as the circle grows)?
3. Code-signing cert: OV (~$200/yr, recommended) — accept the cost?
4. Licence-key gate + kill switch: yes/no (effort vs control)?
5. How many friends / how fast might it spread? (decides how far past
   "Nuitka + sign + strip" to invest — heavier anti-RE is likely
   disproportionate for a small trusted circle.)
6. Who owns rebuilds on dep updates? (the maintainability gap that
   killed the predecessor).

## 10. Effort & honest recommendation

Phases 1–4 are a real, multi-day workstream with **ongoing
maintenance** (each dep/Playwright update can break the freeze; signing
renewals). For a small trusted circle, the high-ROI set is:
**Nuitka standalone + Inno Setup + code signing + stripped build +
licence file**, with the **central-sheet model** as the actual IP moat.
Heavier obfuscation/licensing has steeply diminishing returns.

This is a **separate workstream from the trading pipeline** (M1
market-hours validation + scheduled jobs remain the critical path). I'd
sequence it *after* the core tool is proven in live use — a packaged
installer of an unvalidated tool just multiplies support load.
