@echo off
setlocal
cd /d "%~dp0..\..\"
set "NAV_PY=vendor\csgobot\venv\Scripts\python.exe"
if not exist "%NAV_PY%" set "NAV_PY=.venv\Scripts\python.exe"
if not exist "%NAV_PY%" (
  echo Python environment not found.
  pause
  exit /b 1
)
echo EXPERIMENTAL expanded Dust2. Not all floors or transitions supported. F8 toggle, F10 exit.
"%NAV_PY%" scripts\nav_live.py --drive --roam --expanded-dust2 --seconds 600
pause
