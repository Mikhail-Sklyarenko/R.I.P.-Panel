@echo off
setlocal
cd /d "%~dp0..\..\"
if "%~1"=="" (
  echo Drag a 1280x720 video file onto this BAT to check navigation without game input.
  pause
  exit /b 2
)
set "NAV_PY=vendor\csgobot\venv\Scripts\python.exe"
if not exist "%NAV_PY%" set "NAV_PY=.venv\Scripts\python.exe"
if not exist "%NAV_PY%" (
  echo Python environment not found.
  pause
  exit /b 1
)
"%NAV_PY%" scripts\nav_replay_check.py --video "%~1" --seconds 60
set "NAV_RESULT=%errorlevel%"
pause
exit /b %NAV_RESULT%
