@echo off
REM Promote farm auto-captures into sources\our_cs2 (TRAIN / collector workflow).
REM Requires prior sessions with CSGOBOT_AUTO_CAPTURE=1.
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: csgobot venv not found under vendor\csgobot\venv
  exit /b 1
)

echo.
echo === R.I.P. Panel: BuildOurCs2FromRaw ===
echo Reads:  %CSGOBOT%\data\captures
echo Writes: %CSGOBOT%\yolov8\datasets\sources\our_cs2
echo.

"%PY%" "%CSGOBOT%\yolov8\datasets\filter_promote_our_cs2.py" ^
  --raw-root "%CSGOBOT%\data\captures" ^
  --out-root "%CSGOBOT%\yolov8\datasets\sources\our_cs2" ^
  --prefer-team-t ^
  --allow-empty ^
  --max-empty-pct 15 ^
  --min-ct-share 0.50

if errorlevel 1 (
  echo ERROR: promote failed
  exit /b 1
)

echo.
echo Next:
echo   1) Merge into product set ^(run_product_pipeline / Bootstrap with --source ours=...^)
echo   2) TrainProductModel.bat
echo   3) Soak + promote weights
echo.
exit /b 0
