@echo off
REM Promote hard-neg captures → sources\hard_negatives (empty YOLO labels).
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: csgobot venv not found under vendor\csgobot\venv
  exit /b 1
)

echo.
echo === R.I.P. Panel: BuildHardNegativesFromRaw ===
echo Reads:  %CSGOBOT%\data\captures
echo Writes: %CSGOBOT%\yolov8\datasets\sources\hard_negatives
echo.

"%PY%" "%CSGOBOT%\yolov8\datasets\promote_hard_negatives.py" ^
  --raw-root "%CSGOBOT%\data\captures" ^
  --out-root "%CSGOBOT%\yolov8\datasets\sources\hard_negatives"

if errorlevel 1 (
  echo ERROR: hard-neg promote failed
  exit /b 1
)

echo.
echo Next:
echo   1^) Rebuild product with --source hn=...\hard_negatives
echo   2^) TrainProductModel.bat
echo   3^) Soak FP sites + promote weights
echo   See docs\HARD_NEGATIVES.md
echo.
exit /b 0
