@echo off
REM ====================================================================
REM  AutoRSA GUI launcher (Windows). Double-click this file to start.
REM ====================================================================
cd /d "%~dp0"

REM Make sure uv (installed to %USERPROFILE%\.local\bin) is on PATH even
REM if this window inherited a stale environment.
set "PATH=%PATH%;%USERPROFILE%\.local\bin"

where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo uv is not installed or not on your PATH.
  echo Install it from https://docs.astral.sh/uv/ then run this again.
  echo.
  pause
  exit /b 1
)

echo Syncing dependencies (quick if nothing changed)...
uv sync
if errorlevel 1 (
  echo.
  echo WARNING: dependency sync failed. This is usually a locked file
  echo from OneDrive or a leftover Python process, not a real problem.
  echo Continuing with the already-installed environment...
  echo.
)

echo.
echo Starting AutoRSA GUI - your browser will open automatically.
echo KEEP THIS WINDOW OPEN while using the app. Close it to stop.
echo.
REM --no-sync: don't rebuild the env at run time, which avoids the same
REM OneDrive file-lock error on a normal launch.
uv run --no-sync streamlit run src/gui/app.py

echo.
echo The GUI has stopped.
pause
