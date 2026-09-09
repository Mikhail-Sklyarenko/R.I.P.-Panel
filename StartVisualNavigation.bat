@echo off
setlocal
cd /d "%~dp0"
set "NAV_PY=vendor\csgobot\venv\Scripts\python.exe"
if not exist "%NAV_PY%" set "NAV_PY=.venv\Scripts\python.exe"
if not exist "%NAV_PY%" (
  echo Python environment not found. Use the existing csgobot environment.
  pause
  exit /b 1
)
"%NAV_PY%" scripts\nav_acceptance.py
if errorlevel 1 (
  echo Offline checks failed. See data\nav_acceptance.json.
  pause
  exit /b 1
)
echo Open Dust2 at 1280x720. Place the player in the central MID lane.
echo Hold CapsLock to navigate. Release to pause. F10 exits. Duration: 120 seconds.
"%NAV_PY%" scripts\nav_live.py --drive
set "NAV_RESULT=%errorlevel%"
pause
exit /b %NAV_RESULT%
