@echo off
REM Vault CLI via FarmPanel.exe (frozen) or dev python
cd /d "%~dp0"
if exist "FarmPanel.exe" (
  FarmPanel.exe --vault-cli %*
  exit /b %ERRORLEVEL%
)
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m modules.vault.cli %*
  exit /b %ERRORLEVEL%
)
echo Run from dist\FarmPanel or create .venv in source tree
exit /b 1
