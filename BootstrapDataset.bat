@echo off
REM TRAIN MACHINE ONLY: build product YOLO dataset from external HF source.
REM Does NOT train. Does NOT belong on farm PCs (multi-GB download).
REM Farm fleet: use EnsureWeights.bat instead (~50 MB .pt).
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "DS=%CSGOBOT%\yolov8\datasets"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"
set "PIP=%CSGOBOT%\venv\Scripts\pip.exe"

echo.
echo === R.I.P. Panel: BootstrapDataset (TRAIN ONLY) ===
echo WARNING: downloads multi-GB images. Do NOT run on every farm PC.
echo Farm PCs need EnsureWeights.bat only.
echo.

if not exist "%PY%" (
  echo ERROR: csgobot venv not found.
  echo Create it first:
  echo   cd vendor\csgobot
  echo   python -m venv venv
  echo   venv\Scripts\pip.exe install -r requirements.txt
  echo   venv\Scripts\pip.exe install huggingface_hub
  exit /b 1
)

echo Workdir: %DS%
echo Source:  fvossel/csgo-player-detection  ^(CS2, external, not in git^)
echo.

"%PY%" -c "import huggingface_hub" >nul 2>&1
if errorlevel 1 (
  echo Installing huggingface_hub...
  "%PIP%" install huggingface_hub
  if errorlevel 1 (
    echo ERROR: failed to install huggingface_hub
    exit /b 1
  )
)

"%PY%" "%DS%\run_product_pipeline.py" ^
  --workdir "%DS%" ^
  --hf-repo fvossel/csgo-player-detection ^
  --hf-local-dir hf_raw\fvossel_cs2 ^
  --hf-data-subdir data ^
  --convert-splits train,validation ^
  --out-root product_v1_bootstrap ^
  --classes c,ch,t,th ^
  --train-pct 80 ^
  --val-pct 10 ^
  --dedup-stem ^
  --manifest-out manifests\product_v1_bootstrap_manifest.json

if errorlevel 1 (
  echo.
  echo ERROR: pipeline failed. See messages above.
  exit /b 1
)

echo.
echo OK: product dataset ready on this TRAIN machine
echo   YOLO root:  %DS%\product_v1_bootstrap
echo   data yaml:  %DS%\product_data.yaml
echo   Manifest:   %DS%\manifests\product_v1_bootstrap_manifest.json
echo.
echo Next on TRAIN PC: TrainProductModel.bat
echo Then promote .pt via scripts\promote_weights.py and host URL.
echo Farm fleet never needs this dataset — only EnsureWeights.bat.
echo.
exit /b 0
