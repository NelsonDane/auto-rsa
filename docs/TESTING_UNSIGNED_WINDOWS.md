# Testing the friend build on Windows WITHOUT a code-signing certificate

For the initial testing round you don't have (and don't need) a
code-signing certificate. This is the practical guide to getting an
**unsigned** build to run on a friend's Windows PC — what warnings
appear, the exact clicks to get past them, and whether administrator
rights are needed.

## TL;DR

- **Administrator is NOT required.** The app installs to the user's own
  folders, binds `localhost`, and drives a browser — none of that needs
  elevation. **Do not run it as administrator** (browser automation
  misbehaves under elevation, and it's an unnecessary risk).
- The scary **"Windows protected your PC"** box is Windows **SmartScreen**
  reacting to an *unsigned, low-reputation* file. It has nothing to do
  with admin rights. You get past it with **More info → Run anyway** —
  any standard user can click that.
- The single best way to avoid the warning entirely: after downloading,
  **right-click the file → Properties → check "Unblock" → OK** *before*
  opening it.

---

## Why the warnings happen (so you can explain it to a friend)

Two separate Windows features fire on an unsigned download:

1. **Mark of the Web (MOTW).** Anything downloaded from the internet gets
   an invisible "this came from the internet" tag. That tag is what makes
   SmartScreen and Office/AV treat the file with suspicion.
2. **SmartScreen.** On first run of a tagged, unsigned file that Microsoft
   hasn't seen many times before, it shows the blue *"Windows protected
   your PC"* dialog. A code-signing certificate (especially EV) builds
   reputation that suppresses this — which is why signing is
   "near-mandatory" for a wide audience. For **a few trusted testers**,
   clicking through it once per machine is fine.

Neither is a permission/elevation problem. Clicking "Run anyway" does not
grant admin; it just tells SmartScreen you trust this specific file.

---

## The friend's steps (copy-paste this to your tester)

> **Running AutoRSA (first time)**
>
> Windows will warn you because the app isn't code-signed yet (I'm the
> one who sent it to you — it's safe). Two ways:
>
> **Easiest — remove the warning first:**
> 1. Find the file you downloaded (the `.zip` or `AutoRSA-Setup.exe`).
> 2. **Right-click it → Properties.**
> 3. At the bottom, tick **"Unblock"**, then **OK**.
> 4. Now open it normally. (If it's a `.zip`, unblock the zip *before*
>    extracting, then extract and run.)
>
> **Or click through the warning:**
> 1. Open the file. A blue **"Windows protected your PC"** box appears.
> 2. Click **"More info"**.
> 3. Click **"Run anyway"**.
>
> You will **not** be asked for an administrator password, and you should
> **not** run it as administrator.

---

## If Windows Defender (antivirus) quarantines it

SmartScreen (the blue box) is usually all you hit. Occasionally
**Microsoft Defender Antivirus** will *false-positive* a compiled-Python
executable and quarantine or delete it. This is a known nuisance with
frozen Python apps, not a real infection. Options, in order:

1. **Prefer a Nuitka `--standalone` folder over `--onefile`.** Onefile
   re-extracts to a temp dir on every launch, which trips AV far more
   often. The standalone folder (zipped) is much less likely to be
   flagged. (The installer plan already recommends standalone — keep it.)
2. **Restore from quarantine + add an exclusion:** Windows Security →
   Virus & threat protection → Protection history → restore; then add the
   install folder under Exclusions. (Adding an exclusion *does* prompt for
   admin — that's a one-time Defender setting, not the app needing admin.)
3. **Submit the file to Microsoft** as a false positive
   (https://www.microsoft.com/wdsi/filesubmission). Detection usually
   clears in a day or two, which also helps every other tester.

If a tester keeps getting quarantined, fall back to "run from source"
below for them.

---

## Do I need administrator rights? (No — here's the detail)

| Action | Needs admin? |
|---|---|
| Get past the SmartScreen "Run anyway" box | **No** |
| Install to `%LOCALAPPDATA%\AutoRSA` (per-user, the plan's default) | **No** |
| Run the app (Streamlit on localhost + browser automation) | **No** |
| First-run browser download (patchright/playwright into a user dir) | **No** |
| Install system-wide to `Program Files` | Yes — so **don't**; keep it per-user |
| Add a Defender exclusion (only if AV false-positives) | Yes (one-time Windows setting, not the app) |

**Keep the installer per-user** (`%LOCALAPPDATA%`, no "install for all
users" option) and nothing in the normal flow ever needs elevation.
Running the app as admin is actively worse: Chrome/Chromedriver and
nodriver can fail to attach or behave differently under an elevated
token, and a trading app holding your broker logins has no reason to run
elevated.

---

## Alternatives for the initial testing round

You have three ways to get the build in front of a tester; pick per how
technical they are.

1. **Unsigned standalone zip (recommended for non-technical friends).**
   Send the zipped Nuitka `--standalone` folder (or the Inno `.exe` once
   built). They Unblock → extract → run. ~3 extra clicks, one time. This
   is closest to the real friend experience, so it also validates your
   packaging.
2. **Run from source (recommended for a technical friend / your own
   second machine).** No SmartScreen at all — it's just Python:
   ```powershell
   git clone <repo>; cd auto-rsa
   py -3.12 -m venv .venv; .\.venv\Scripts\activate
   pip install -r requirements.txt
   streamlit run src/gui/app.py
   ```
   Zero Windows-security friction; good for shaking out logic bugs before
   you deal with packaging.
3. **Sideload without MOTW.** Copying the folder via a USB stick (or a
   LAN share configured as trusted) often arrives *without* the internet
   tag, so no SmartScreen. Least reliable (depends on the transfer), but
   handy for a machine you can walk up to.

For the **friend build specifically**, ship it with the friend profile on
(`SIMPLE_MODE_DEFAULT` + `REQUIRE_LICENSE_TO_TRADE` true) so the tester
lands in Simple Mode with the setup wizard and license gate — see
`docs/SIMPLE_MODE_DESIGN.md`.

---

## When to actually buy a certificate

You don't need one for a handful of trusted testers who can follow the
Unblock/Run-anyway steps above. Buy an **OV code-signing certificate
(~$200/yr)** when either is true:

- the circle grows past people you can hand-hold, or
- the repeated SmartScreen/Defender friction is costing you more than the
  cert.

Signing removes the SmartScreen box (immediately for EV, and for OV once
a little reputation accrues) and sharply cuts Defender false-positives.
Until then, unsigned + these instructions is a perfectly workable testing
path. See `docs/WINDOWS_INSTALLER_DESIGN.md` §5 for where signing fits in
the full build.
