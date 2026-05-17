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
  echo Dependency sync failed. See the message above.
  pause
  exit /b 1
)

echo.
echo Starting AutoRSA GUI - your browser will open automatically.
echo KEEP THIS WINDOW OPEN while using the app. Close it to stop.
echo.
uv run streamlit run src/gui/app.py

echo.
echo The GUI has stopped.
pause
