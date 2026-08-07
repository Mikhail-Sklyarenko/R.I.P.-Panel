@echo off
REM Import empty-label frames from a YOLO dataset (e.g. product_v1_bootstrap)
REM into sources\hard_negatives. Preserves train/val/test. Writes empty labels.
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"
set "DATASET=%~1"

if "%DATASET%"=="" (
  echo.
  echo Usage: ImportEmptyYoloSplits.bat ^<path-to-product_v1_bootstrap-or-parent^>
  echo.
  echo Example:
  echo   ImportEmptyYoloSplits.bat D:\datasets\product_v1_bootstrap
  echo   ImportEmptyYoloSplits.bat E:\  ^(if E:\ has train\ val\ test\^)
  echo.
  echo Writes: %CSGOBOT%\yolov8\datasets\sources\hard_negatives
  echo See: docs\HARD_NEGATIVES.md
  exit /b 1
)

if not exist "%PY%" (
  echo ERROR: csgobot venv not found under vendor\csgobot\venv
  exit /b 1
)

if not exist "%DATASET%" (
  echo ERROR: dataset path not found: %DATASET%
  exit /b 1
)

echo.
echo === R.I.P. Panel: ImportEmptyYoloSplits ===
echo Source: %DATASET%
echo Out:    %CSGOBOT%\yolov8\datasets\sources\hard_negatives
echo.

"%PY%" "%CSGOBOT%\yolov8\datasets\import_empty_yolo_splits.py" ^
  --dataset-root "%DATASET%" ^
  --out-root "%CSGOBOT%\yolov8\datasets\sources\hard_negatives" ^
  --summary "%CSGOBOT%\yolov8\datasets\manifests\hard_negatives_bootstrap_summary.json"

if errorlevel 1 (
  echo ERROR: import failed
  exit /b 1
)

echo.
echo Next on TRAIN PC:
echo   1^) BuildProductWithHardNegatives.bat
echo   2^) TrainProductModel.bat ^(point --data at product_v2_hn yaml^)
echo   3^) Soak Mirage crates / Dust2 car, then promote weights
echo   Farm: EnableFpGuard.bat until new .pt is live
echo.
exit /b 0
