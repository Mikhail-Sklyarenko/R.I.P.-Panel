@echo off
REM Extract dataset RARs from USB into Train PC project (one-time setup).
setlocal EnableExtensions
cd /d "%~dp0"

set "DS=%~dp0vendor\csgobot\yolov8\datasets"
set "STAGING=%~dp0dataset_staging"

if not exist "%DS%" mkdir "%DS%"
if not exist "%STAGING%" mkdir "%STAGING%"

echo.
echo === Extract dataset archives ===
echo Place RARs on USB or set SOURCE folder below.
echo.

set "SOURCE=E:\"
if exist "D:\product_v1_bootstrap.rar" set "SOURCE=D:\"
if exist "E:\product_v1_bootstrap.rar" set "SOURCE=E:\"

if not exist "%SOURCE%product_v1_bootstrap.rar" (
  echo ERROR: product_v1_bootstrap.rar not found in %SOURCE%
  echo Copy RARs from USB or edit SOURCE= in this bat file.
  exit /b 1
)

where bsdtar >nul 2>&1
if errorlevel 1 (
  echo Using WinRAR if installed...
  set "UNRAR=C:\Program Files\WinRAR\UnRAR.exe"
  if not exist "%UNRAR%" (
    echo ERROR: need bsdtar or WinRAR to extract
    exit /b 1
  )
  "%UNRAR%" x -y "%SOURCE%product_v1_bootstrap.rar" "%DS%\"
  "%UNRAR%" x -y "%SOURCE%hard_negatives.rar" "%STAGING%\"
  "%UNRAR%" x -y "%SOURCE%our_cs2_BAD_DO_NOT_USE.rar" "%STAGING%\"
  "%UNRAR%" x -y "%SOURCE%captures.rar" "%STAGING%\"
) else (
  bsdtar -xf "%SOURCE%product_v1_bootstrap.rar" -C "%DS%"
  bsdtar -xf "%SOURCE%hard_negatives.rar" -C "%STAGING%"
  bsdtar -xf "%SOURCE%our_cs2_BAD_DO_NOT_USE.rar" -C "%STAGING%"
  bsdtar -xf "%SOURCE%captures.rar" -C "%STAGING%"
)

echo.
echo Verify bootstrap images:
dir /b "%DS%\product_v1_bootstrap\train\images\*.png" 2>nul | find /c /v ""
echo.
echo Next:
echo   RunSortDatasetExport.bat
echo   BuildProductWithHardNegatives.bat
echo   TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_golden_v1
echo.
exit /b 0
