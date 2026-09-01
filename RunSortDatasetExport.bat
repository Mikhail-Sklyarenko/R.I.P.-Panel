@echo off
REM Re-sort extracted archives into hard_negatives + quarantine manifests (TRAIN PC or Mac).
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0vendor\csgobot\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo === RunSortDatasetExport ===
"%PY%" "%~dp0vendor\csgobot\yolov8\datasets\sort_dataset_export.py" ^
  --staging "%~dp0dataset_staging" ^
  --bootstrap "%~dp0vendor\csgobot\yolov8\datasets\product_v1_bootstrap" ^
  --export "%~dp0dataset_export" ^
  --in-place

if errorlevel 1 (
  echo ERROR: sort failed
  exit /b 1
)

echo.
echo OK. See dataset_export\SORT_REPORT.md
echo Next: BuildProductWithHardNegatives.bat then TrainProductModel.bat
exit /b 0
