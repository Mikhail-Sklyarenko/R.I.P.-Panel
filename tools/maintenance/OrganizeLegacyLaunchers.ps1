$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Moves = Get-Content (Join-Path $Root 'docs/LAUNCHER_MIGRATION.json') -Raw | ConvertFrom-Json
$Backup = Join-Path $Root ('data/maintenance-backup/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
foreach ($Move in $Moves) {
    $Old = Join-Path $Root $Move.from
    $New = Join-Path $Root $Move.to
    if ((Test-Path -LiteralPath $Old -PathType Leaf) -and (Test-Path -LiteralPath $New -PathType Leaf)) {
        New-Item -ItemType Directory -Force -Path $Backup | Out-Null
        Move-Item -LiteralPath $Old -Destination (Join-Path $Backup $Move.from)
        Write-Host "Archived old launcher: $($Move.from)"
    }
}
Write-Host 'Ready. Start FarmPanel.bat in the project root.'
