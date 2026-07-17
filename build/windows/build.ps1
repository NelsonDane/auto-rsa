# build.ps1 — build the AutoRSA one-click Windows app with Nuitka.
#
#   Run on Windows (PowerShell), NOT in this Linux sandbox:
#       cd auto-rsa
#       .\build\windows\build.ps1                 # friend build (default)
#       .\build\windows\build.ps1 -Profile pro    # full/pro build
#       .\build\windows\build.ps1 -Console        # keep a console window (debug)
#
# Produces a Nuitka --standalone FOLDER at build\out\launcher.dist\ with
# AutoRSA.exe inside. Feed that folder to Inno Setup (AutoRSA.iss) to make
# the installer, or zip it for an unsigned test drop.
#
# See BUILD.md for prerequisites and the known-fragile points (Streamlit +
# Nuitka is the part most likely to need a flag tweak on the first build).

param(
    [ValidateSet("friend", "pro")] [string] $Profile = "friend",
    [string] $Version = "0.1.0",
    [switch] $Console
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$Stage    = Join-Path $RepoRoot "build\stage"
$OutDir   = Join-Path $RepoRoot "build\out"

Write-Host "== AutoRSA build: profile=$Profile version=$Version ==" -ForegroundColor Cyan

# 1) Stage a clean copy of the source (so we can patch the build profile
#    WITHOUT touching your working tree, and strip what shouldn't ship).
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
# robocopy exit codes 0-7 are success; PowerShell treats non-zero as error.
robocopy "$RepoRoot\src" "$Stage\src" /E /NFL /NDL /NJH /NJS `
    /XD __pycache__ .git .venv node_modules | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
Copy-Item "$PSScriptRoot\launcher.py" "$Stage\launcher.py"

# 2) Apply the build profile. The FRIEND build bakes Simple Mode + the
#    license-required gate ON so a friend can't flip them off.
if ($Profile -eq "friend") {
    python "$PSScriptRoot\apply_friend_profile.py" "$Stage\src\license\_keys.py"
}

# 3) Nuitka standalone. Streamlit runs app.py by EXECUTING it, so app.py
#    ships as a data file (source); everything it imports is compiled into
#    the binary. The exe multiplexes: `AutoRSA.exe --engine <json>` runs
#    the trade engine (see launcher.py / runner._engine_command).
$ConsoleFlag = if ($Console) { "--windows-console-mode=force" } `
               else { "--windows-console-mode=disable" }

Push-Location $Stage
try {
    python -m nuitka `
        --standalone `
        --assume-yes-for-downloads `
        --output-dir="$OutDir" `
        --output-filename="AutoRSA.exe" `
        --product-name="AutoRSA" `
        --company-name="AutoRSA" `
        --file-version="$Version" `
        --product-version="$Version" `
        $ConsoleFlag `
        --include-package=src `
        --include-package=streamlit `
        --include-package-data=streamlit `
        --include-package-data=altair `
        --include-package-data=pandas `
        --include-package-data=pyarrow `
        --include-data-files="src/gui/app.py=src/gui/app.py" `
        --include-module=src.gui.core.engine_proc `
        --nofollow-import-to="pytest" `
        --nofollow-import-to="*.tests" `
        "launcher.py"
    if ($LASTEXITCODE -ne 0) { throw "Nuitka failed ($LASTEXITCODE)" }
}
finally { Pop-Location }

Write-Host "`nDone. Standalone folder:" -ForegroundColor Green
Write-Host "  $OutDir\launcher.dist\  (run AutoRSA.exe)"
Write-Host "Next: build the installer with Inno Setup (build\windows\AutoRSA.iss)," -ForegroundColor Green
Write-Host "or zip launcher.dist for an unsigned test drop (see docs/TESTING_UNSIGNED_WINDOWS.md)."
