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
set "NAV_RESULT=%errorlevel%"
pause
exit /b %NAV_RESULT%
