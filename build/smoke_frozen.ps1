# Optional smoke on Windows after build (no GUI interaction)
# Usage: powershell -File build\smoke_frozen.ps1

$ErrorActionPreference = "Stop"
$Dist = Join-Path (Split-Path -Parent $PSScriptRoot) "dist\FarmPanel"
$Exe = Join-Path $Dist "FarmPanel.exe"
if (-not (Test-Path $Exe)) {
    throw "Run build\build_windows.ps1 first"
}
& $Exe --vault-cli list
if ($LASTEXITCODE -ne 0) { throw "vault-cli list failed" }
Write-Host "smoke_frozen: OK"
