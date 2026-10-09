@echo off
setlocal
cd /d "%~dp0"
if exist "main.py" (
  if exist ".venv\Scripts\pythonw.exe" (
    if exist "launch_panel.pyw" (
      start "" ".venv\Scripts\pythonw.exe" "%~dp0launch_panel.pyw" %*
      exit /b 0
    )
    echo Incomplete update: launch_panel.pyw is missing.
  ) else (
    echo Panel Python missing. Run: py -3.11 -m venv .venv
    echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
  )
) else if exist "FarmPanel.exe" (
  start "" "%~dp0FarmPanel.exe" %*
  exit /b 0
) else (
  echo Incomplete installation: main.py or FarmPanel.exe required.
)
pause
exit /b 1
