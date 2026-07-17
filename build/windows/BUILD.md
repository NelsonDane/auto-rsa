# Building the AutoRSA one-click Windows app

This turns the app into `AutoRSA-Setup.exe` — a per-user, no-admin
installer a non-technical friend can double-click. The **friend** profile
bakes in Simple Mode + the license gate; the **pro** profile is the full
app.

> **Status: pipeline scaffolded, needs a first build on Windows.**
> The launcher, the friend-profile patch, and the frozen-engine spawn are
> unit-tested and correct. The Nuitka + Inno Setup steps below cannot be
> run or validated in the dev sandbox (Linux) — expect to iterate a little
> on the Nuitka flags on your first Windows build. The fragile points are
> called out in §5.

Everything here runs **on Windows**, not in the Linux dev environment.

## 1. Prerequisites (one time)

- **Python 3.12** (the app targets 3.12; 3.14 has dependency issues).
- **A C compiler for Nuitka.** Easiest: `python -m nuitka` will offer to
  download a MinGW-w64 toolchain on first run (`--assume-yes-for-downloads`
  accepts it). Or install Visual Studio Build Tools.
- **Git submodules checked out** (the vendored broker libs):
  `git submodule update --init --recursive`.
- **Dependencies installed** into the Python you'll build with:
  `pip install -r requirements.txt` (or `uv sync`), plus `pip install nuitka`.
- **Inno Setup 6** (https://jrsoftware.org/isinfo.php) for the installer —
  gives you `iscc.exe`.

## 2. Validate the launcher FROM SOURCE first (de-risks everything)

Before touching Nuitka, prove the launcher + Streamlit-start logic works
as plain Python:

```powershell
python build\windows\launcher.py
```

Your browser should open `http://127.0.0.1:8501` with the app. If that
works, any later failure is a *packaging* problem (Nuitka flags), not a
logic problem — a much smaller search space. Ctrl+C to stop.

To preview the **friend experience** from source, force the flags on:

```powershell
$env:RSA_SIMPLE_MODE = "1"          # Simple Mode UI + setup wizard
python build\windows\launcher.py
```

## 3. Build the standalone app

```powershell
.\build\windows\build.ps1                 # friend build (default)
.\build\windows\build.ps1 -Profile pro    # full/pro build
.\build\windows\build.ps1 -Console        # keep a console window for debugging
```

`build.ps1`:
1. stages a clean copy of `src\` (so it can patch the profile without
   touching your working tree, and strip `__pycache__`/`.git`),
2. for the friend build, runs `apply_friend_profile.py` to set
   `SIMPLE_MODE_DEFAULT` and `REQUIRE_LICENSE_TO_TRADE` to True in the
   staged `_keys.py` (baked in — a friend can't flip them off),
3. runs Nuitka `--standalone`.

Output: `build\out\launcher.dist\` containing `AutoRSA.exe`.

**Smoke-test the compiled app before packaging it:**
```powershell
.\build\out\launcher.dist\AutoRSA.exe
```
The GUI should open. Then **place a dry-run trade** — that exercises the
engine subprocess (`AutoRSA.exe --engine …`), which is the part most
likely to break in a frozen build (§5).

## 4. Make the installer

```powershell
iscc build\windows\AutoRSA.iss
```
Output: `build\out\AutoRSA-Setup.exe` — per-user, no admin, unsigned.

Hand it to a tester with the steps in `docs/TESTING_UNSIGNED_WINDOWS.md`
(no cert needed; "Unblock" or "More info → Run anyway"; never run as
admin). Or, for an even lighter test drop, just zip `launcher.dist\`.

## 5. Known-fragile points (where a first build usually needs a tweak)

1. **Streamlit runs `app.py` by executing the file.** So `app.py` ships as
   a *data file* (`--include-data-files=src/gui/app.py=...`) — it stays
   source-visible — while everything it imports is compiled into the
   binary (`--include-package=src`). If Streamlit can't find or exec it,
   the GUI won't start. If Nuitka misses a dynamically-imported Streamlit
   dependency, you'll see an ImportError at launch — add the missing
   package with another `--include-package=` / `--include-package-data=`
   and rebuild.
2. **The engine subprocess.** A compiled exe can't do `python -m …`, so
   the app re-invokes itself: `AutoRSA.exe --engine <json>` runs the trade
   engine (handled in `launcher.py`; the runner picks this form when
   `AUTORSA_FROZEN=1`, which the compiled launcher sets). If a dry-run
   trade does nothing or errors immediately, this is the first place to
   look — run with `-Console` to see the engine's output.
3. **Browser brokers need their engines.** Chase/Fidelity/SoFi/Wells Fargo
   drive patchright/playwright/nodriver + system Chrome, ~hundreds of MB.
   The friend build hides those behind the "Advanced brokers" expander, so
   the base install stays small and API-only. If you want browser brokers
   to work in the packaged app, either bundle the browser engines or have
   the app fetch them on first use — not wired into this build yet.
4. **Per-user data location.** The app stores its vault/ledger/logs in
   `creds\` next to the exe (under `%LOCALAPPDATA%\AutoRSA`, which is
   user-writable). `AutoRSA.iss` preserves `creds\` across uninstall so a
   reinstall/update never wipes a friend's vault or license. (Moving data
   to `%APPDATA%` would need the app to honor a data-dir env var — a
   future refinement, not required for testing.)
5. **Antivirus false-positives.** Use `--standalone` (a folder), never
   `--onefile` — onefile re-extracts to temp on every launch and trips
   Defender far more often. See `docs/TESTING_UNSIGNED_WINDOWS.md`.

## 6. Signing (later, optional)

Unsigned is fine for a handful of trusted testers. When the circle grows,
buy an OV code-signing certificate (~$200/yr) and sign both
`launcher.dist\AutoRSA.exe` and `AutoRSA-Setup.exe` with `signtool` — that
removes the SmartScreen prompt and cuts Defender false-positives. See
`docs/WINDOWS_INSTALLER_DESIGN.md` §5.
