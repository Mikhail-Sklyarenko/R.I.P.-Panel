@echo off
REM One-click CS2 dataset bootstrap (csgobot-style: data not in git).
REM Downloads approved HF source, converts to YOLO, builds product_v1_bootstrap,
REM audits quality, writes immutable manifest.
setlocal EnableExtensions
cd /d "%~dp0"

set "CSGOBOT=%~dp0vendor\csgobot"
set "DS=%CSGOBOT%\yolov8\datasets"
set "PY=%CSGOBOT%\venv\Scripts\python.exe"
set "PIP=%CSGOBOT%\venv\Scripts\pip.exe"

if not exist "%PY%" (
  echo ERROR: csgobot venv not found.
  echo Create it first:
  echo   cd vendor\csgobot
  echo   python -m venv venv
  echo   venv\Scripts\pip.exe install -r requirements.txt
  echo   venv\Scripts\pip.exe install "huggingface_hub[cli]"
  exit /b 1
)

echo.
echo === R.I.P. Panel: dataset bootstrap ===
echo Workdir: %DS%
echo Source:  fvossel/csgo-player-detection  ^(CS2, external, not in git^)
echo.

"%PIP%" show huggingface_hub >nul 2>&1
if errorlevel 1 (
  echo Installing huggingface_hub...
  "%PIP%" install "huggingface_hub[cli]"
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
echo OK: dataset ready
echo   YOLO root:  %DS%\product_v1_bootstrap
echo   Manifest:   %DS%\manifests\product_v1_bootstrap_manifest.json
echo.
echo Next ^(optional^): put your own CS2 captures into
echo   %DS%\sources\our_cs2\train\images + labels
echo then re-run with --source ours=...  ^(see docs\CS2_DATASET_PIPELINE.md^)
echo.
exit /b 0
