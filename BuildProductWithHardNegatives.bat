@echo off
REM Merge bootstrap + our_cs2 + hard_negatives → product_v2_hn (TRAIN PC).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"
set "DS=%CSGOBOT%\yolov8\datasets"

if not exist "%PY%" (
  echo ERROR: csgobot venv not found under vendor\csgobot\venv
  exit /b 1
)

set "BOOT=%DS%\product_v1_bootstrap"
set "OURS=%DS%\sources\our_cs2"
set "HN=%DS%\sources\hard_negatives"
set "OUT=%DS%\product_v2_hn"

if not exist "%BOOT%\train\images\" (
  echo ERROR: missing %BOOT% — run BootstrapDataset.bat first
  exit /b 1
)

dir /b "%HN%\train\images\*.png" "%HN%\train\images\*.jpg" >nul 2>&1
if errorlevel 1 (
  echo ERROR: hard_negatives has no images — run ImportEmptyYoloSplits.bat or BuildHardNegativesFromRaw.bat
  exit /b 1
)

echo.
echo === R.I.P. Panel: BuildProductWithHardNegatives ===
echo bootstrap: %BOOT%
echo our_cs2:   %OURS%  ^(optional if present^)
echo hn:        %HN%
echo out:       %OUT%
echo.

set "SRC_ARGS=--source bootstrap=%BOOT% --source hn=%HN%"
if exist "%OURS%\train\images\" (
  dir /b "%OURS%\train\images\*.png" "%OURS%\train\images\*.jpg" >nul 2>&1
  if not errorlevel 1 (
    set "SRC_ARGS=!SRC_ARGS! --source ours=%OURS%"
  ) else (
    echo NOTE: our_cs2 images missing — building bootstrap + hn only
  )
) else (
  echo NOTE: our_cs2 empty/missing — building bootstrap + hn only
)

"%PY%" "%DS%\build_product_dataset.py" !SRC_ARGS! --out-root "%OUT%" --classes c,ch,t,th --copy-images

if errorlevel 1 (
  echo ERROR: product build failed
  exit /b 1
)

REM YOLO data yaml (TRAIN only) — points at product_v2_hn
> "%DS%\product_data_hn.yaml" (
  echo # YOLO data config: bootstrap + hard_negatives ^(± our_cs2^). TRAIN MACHINE ONLY.
  echo path: product_v2_hn
  echo train: train/images
  echo val: val/images
  echo test: test/images
  echo.
  echo nc: 4
  echo names:
  echo   0: c
  echo   1: ch
  echo   2: t
  echo   3: th
)

echo.
echo OK: product at %OUT%
echo YAML: %DS%\product_data_hn.yaml
echo Next:
echo   TrainProductModel.bat --data "%DS%\product_data_hn.yaml" --name product_fpfix_v1
echo   Soak Mirage crates / Dust2 car, then promote weights
echo   See docs\HARD_NEGATIVES.md
echo.
exit /b 0
