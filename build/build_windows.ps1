# B-PACKAGE: build dist/FarmPanel/ on Windows (Python 3.11)
# Usage: powershell -ExecutionPolicy Bypass -File build\build_windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Farm Panel build - root: $Root"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    py -3.11 -m venv .venv
}

$py = ".\.venv\Scripts\python.exe"
$icon = Join-Path $Root "resources\app\farm_panel.ico"
& $py -m pip install -q -r requirements.txt -r build\requirements-build.txt

Write-Host "Regenerating app icon..."
& $py build\make_app_icon.py
if (-not (Test-Path $icon)) {
    throw "Icon not found: $icon"
}

Write-Host "Running PyInstaller..."
& $py -m PyInstaller build\farm_panel.spec --noconfirm --clean --icon $icon
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed; refusing to package stale EXE" }

$Dist = Join-Path $Root "dist\FarmPanel"
if (-not (Test-Path $Dist)) {
    throw "dist\FarmPanel not found after PyInstaller"
}

function Copy-Tree($Src, $Dest) {
    if (Test-Path $Src) {
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        Copy-Item -Path (Join-Path $Src "*") -Destination $Dest -Recurse -Force
    }
}

Write-Host "Copying portable assets..."
Copy-Tree (Join-Path $Root "resources") (Join-Path $Dist "resources")

$LooterSrc = Join-Path $Root "vendor\looter"
$LooterDest = Join-Path $Dist "vendor\looter"
New-Item -ItemType Directory -Force -Path $LooterDest | Out-Null
Copy-Item (Join-Path $LooterSrc "looter_core.js") $LooterDest -Force
Copy-Item (Join-Path $LooterSrc "package.json") $LooterDest -Force

# Ship worker source/resources; environments, models and user data stay local.
$CsgobotSrc = Join-Path $Root "vendor\csgobot"
$CsgobotDest = Join-Path $Dist "vendor\csgobot"
& robocopy $CsgobotSrc $CsgobotDest /E /XD venv .venv __pycache__ .git data datasets runs /XF *.pyc *.pt /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw "Failed to copy csgobot worker" }
# Studio is launched from the panel as a separate diagnostic process.
& robocopy (Join-Path $Root "scripts") (Join-Path $Dist "scripts") /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw "Failed to copy diagnostic scripts" }

New-Item -ItemType Directory -Force -Path (Join-Path $Dist "data") | Out-Null
Copy-Item (Join-Path $Root "build\README_RUN.txt") $Dist -Force

Copy-Item (Join-Path $Root "FarmPanel.bat") $Dist -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "vault_cli.bat") $Dist -Force -ErrorAction SilentlyContinue

$ExePath = Join-Path $Dist "FarmPanel.exe"
$RceditDir = Join-Path $PSScriptRoot "tools"
$Rcedit = Join-Path $RceditDir "rcedit-x64.exe"
if (-not (Test-Path $RceditDir)) {
    New-Item -ItemType Directory -Force -Path $RceditDir | Out-Null
}
if (-not (Test-Path $Rcedit)) {
    Write-Host "Downloading rcedit (one-time)..."
    Invoke-WebRequest -Uri "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe" -OutFile $Rcedit
}
Write-Host "Applying EXE file icon..."
& $Rcedit $ExePath --set-icon $icon

$DocsDest = Join-Path $Dist "docs"
New-Item -ItemType Directory -Force -Path $DocsDest | Out-Null
Copy-Item (Join-Path $Root "docs\WINGMAN_FLEET_MVP.md") $DocsDest -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "docs\PROJECT_GUIDE.md") $DocsDest -Force -ErrorAction SilentlyContinue

Write-Host "Done: $ExePath"
Write-Host 'If Explorer still shows the old icon: close Explorer, reopen the folder, or log off/on.'
Write-Host 'Next: cd vendor\looter; npm install (in dist or source tree)'
Write-Host 'Wingman Inferno fleet (4 PCs): see docs/WINGMAN_FLEET_MVP.md — open TCP 8790 on the coordinator PC.'
