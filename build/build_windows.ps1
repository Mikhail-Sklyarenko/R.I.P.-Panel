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
& $py -m pip install -q -r requirements.txt -r build\requirements-build.txt

Write-Host "Running PyInstaller..."
& $py -m PyInstaller build\farm_panel.spec --noconfirm

$Dist = Join-Path $Root "dist\FarmPanel"
if (-not (Test-Path $Dist)) {
    throw "dist\FarmPanel not found after PyInstaller"
}

function Copy-Tree($Src, $Dest) {
    if (Test-Path $Src) {
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        Copy-Item -Path $Src -Destination $Dest -Recurse -Force
    }
}

Write-Host "Copying portable assets..."
Copy-Tree (Join-Path $Root "resources") (Join-Path $Dist "resources")

$LooterSrc = Join-Path $Root "vendor\looter"
$LooterDest = Join-Path $Dist "vendor\looter"
New-Item -ItemType Directory -Force -Path $LooterDest | Out-Null
Copy-Item (Join-Path $LooterSrc "looter_core.js") $LooterDest -Force
Copy-Item (Join-Path $LooterSrc "package.json") $LooterDest -Force

$CsgobotReadme = Join-Path $Root "vendor\csgobot\README.md"
if (Test-Path $CsgobotReadme) {
    $CsgobotDest = Join-Path $Dist "vendor\csgobot"
    New-Item -ItemType Directory -Force -Path $CsgobotDest | Out-Null
    Copy-Item $CsgobotReadme $CsgobotDest -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $Dist "data") | Out-Null
Copy-Item (Join-Path $Root "build\README_RUN.txt") $Dist -Force

Copy-Item (Join-Path $Root "FarmPanel.bat") $Dist -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "vault_cli.bat") $Dist -Force -ErrorAction SilentlyContinue

Write-Host "Done: $Dist\FarmPanel.exe"
Write-Host 'Next: cd vendor\looter; npm install (in dist or source tree)'
