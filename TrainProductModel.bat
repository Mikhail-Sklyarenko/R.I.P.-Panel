@echo off
REM TRAIN MACHINE ONLY: fine-tune YOLO on product_v1_bootstrap.
REM Farm PCs must NOT run this. Farms use EnsureWeights.bat (~50 MB .pt only).
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: csgobot venv not found. Create vendor\csgobot\venv first.
  exit /b 1
)

if not exist "%CSGOBOT%\yolov8\datasets\product_v1_bootstrap\train\images" (
  echo ERROR: product dataset missing.
  echo On this TRAIN PC run BootstrapDataset.bat first.
  exit /b 1
)

if not exist "%CSGOBOT%\yolov8\cs2_yolov8m_640_augmented_v4.pt" (
  echo Base weights missing — fetching via EnsureWeights...
  call "%~dp0EnsureWeights.bat"
  if errorlevel 1 exit /b 1
)

echo.
echo === R.I.P. Panel: TrainProductModel (TRAIN ONLY) ===
echo Dataset stays on this machine. Fleet gets only the resulting .pt.
echo.

"%PY%" "%CSGOBOT%\yolov8\train_product.py" %*
exit /b %ERRORLEVEL%
