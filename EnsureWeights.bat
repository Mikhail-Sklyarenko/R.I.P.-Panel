@echo off
REM Farm PC: ensure production YOLO weights (~50 MB). NEVER downloads the training dataset.
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0vendor\csgobot\venv\Scripts\python.exe" set "PY=%~dp0vendor\csgobot\venv\Scripts\python.exe"
if not defined PY set "PY=python"

echo.
echo === R.I.P. Panel: EnsureWeights (farm) ===
echo Downloads ONLY the active .pt from weights_registry.json
echo Dataset / BootstrapDataset is NOT used on farm PCs.
echo.

"%PY%" "%~dp0scripts\ensure_weights.py" %*
if errorlevel 1 (
  echo.
  echo ERROR: weights not ready.
  exit /b 1
)

echo.
echo OK: farm weights ready. Run FarmPanel.bat as usual.
exit /b 0
