param(
    [int]$Limit = 12,
    [switch]$SyncCatalog,
    [switch]$DryRun,
    [switch]$Generate,
    [switch]$ReviewAmbiguousFields
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

Set-Location -LiteralPath $projectRoot

function Invoke-AlphaOs {
    & $alphaOs @args
    if ($LASTEXITCODE -ne 0) {
        throw "Lenh alpha-os that bai voi ma $LASTEXITCODE."
    }
}

if ($SyncCatalog) {
    $credentialLines = Get-Content -LiteralPath $envFile
    foreach ($key in @('BRAIN_EMAIL', 'BRAIN_PASSWORD')) {
        if (-not ($credentialLines -match "^$key=.+")) {
            throw "Thieu $key trong .env. Khong dien vao .env.example."
        }
    }
    Invoke-AlphaOs catalog sync --region USA --universe TOP3000 --delay 1
}

# Build deterministic operator/field/path/motif knowledge first. This command
# is local-only and is safe even for a dry run.
Invoke-AlphaOs knowledge build
Invoke-AlphaOs research cycle-plan --budget $Limit

if ($ReviewAmbiguousFields -and -not $DryRun) {
    Invoke-AlphaOs knowledge review-fields --limit 20
}

if ($Generate -and -not $DryRun) {
    # v2 agent: Gemini creates hypotheses and AlphaPlans only. FASTEXPR is
    # compiled locally and exactly one first-pass plan is allowed per card.
    Invoke-AlphaOs agent run --count $Limit --per-card 1
}

Invoke-AlphaOs simulate --limit $Limit --dry-run

if ($DryRun) {
    Write-Output "Da kiem tra co so tri thuc, ke hoach nghien cuu va hang doi. Khong goi Gemini, khong gui mo phong."
    Invoke-AlphaOs status
    return
}

$credentialLines = Get-Content -LiteralPath $envFile
foreach ($key in @('BRAIN_EMAIL', 'BRAIN_PASSWORD')) {
    if (-not ($credentialLines -match "^$key=.+")) {
        throw "Thieu $key trong .env. Khong dien vao .env.example."
    }
}

Invoke-AlphaOs simulate --limit $Limit
Invoke-AlphaOs refresh --limit $Limit
Invoke-AlphaOs review --limit $Limit
# Rebuild empirical motif statistics after fresh evidence is available.
Invoke-AlphaOs knowledge build
Invoke-AlphaOs research cycle-plan --budget $Limit
Invoke-AlphaOs export --status tested --limit $Limit --output data/exports/alpha_tested.csv
Invoke-AlphaOs export --status promoted --limit $Limit --output data/exports/alpha_promoted.csv
Invoke-AlphaOs status
