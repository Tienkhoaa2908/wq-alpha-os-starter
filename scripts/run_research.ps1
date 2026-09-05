param(
    [int]$Limit = 8,
    [switch]$SyncCatalog,
    [switch]$DryRun,
    [switch]$Generate
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$alphaOs = Join-Path $projectRoot '.venv\Scripts\alpha-os.exe'
$envFile = Join-Path $projectRoot '.env'

if ($Limit -lt 1) {
    throw "Limit phai lon hon 0."
}

if (-not (Test-Path -LiteralPath $alphaOs)) {
    throw "Chua co chuong trinh. Chay: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ."
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Thieu tep .env trong thu muc du an."
}
$credentialLines = Get-Content -LiteralPath $envFile
foreach ($key in @('BRAIN_EMAIL', 'BRAIN_PASSWORD')) {
    if (-not ($credentialLines -match "^$key=.+")) {
        throw "Thieu $key trong .env. Khong dien vao .env.example."
    }
}

Set-Location -LiteralPath $projectRoot

function Invoke-AlphaOs {
    & $alphaOs @args
    if ($LASTEXITCODE -ne 0) {
        throw "Lenh alpha-os that bai voi ma $LASTEXITCODE."
    }
}

if ($SyncCatalog) {
    Invoke-AlphaOs catalog sync --region USA --universe TOP3000 --delay 1
}

if ($Generate -and -not $DryRun) {
    Invoke-AlphaOs agent run --count $Limit --per-card 2
}

Invoke-AlphaOs simulate --limit $Limit --dry-run

if ($DryRun) {
    Write-Output "Da kiem tra hang doi. Khong gui mo phong that (chi kiem tra)."
    Invoke-AlphaOs status
    return
}

Invoke-AlphaOs simulate --limit $Limit
Invoke-AlphaOs refresh --limit $Limit
Invoke-AlphaOs review --limit $Limit
Invoke-AlphaOs export --status tested --limit $Limit --output data/exports/alpha_tested.csv
Invoke-AlphaOs export --status promoted --limit $Limit --output data/exports/alpha_promoted.csv
Invoke-AlphaOs status
