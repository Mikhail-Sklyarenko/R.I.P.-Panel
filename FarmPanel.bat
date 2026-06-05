@echo off
REM Dev launcher (source tree). For distribution use dist\FarmPanel\FarmPanel.exe
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" main.py %*
) else if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" main.py %*
) else (
  echo Create venv: py -3.11 -m venv .venv
  echo pip install -r requirements.txt
  exit /b 1
)
