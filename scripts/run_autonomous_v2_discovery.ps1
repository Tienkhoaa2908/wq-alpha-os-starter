param(
    [int]$Count = 6,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
if ($Count -ne 6) {
    throw 'The first autonomous breadth batch is fixed at exactly 6 candidates.'
}

$branch = (git branch --show-current).Trim()
if ($branch -ne 'alpha-research-v2') {
    throw "Current branch is '$branch'. Switch to alpha-research-v2 first."
}

Write-Host '[1/4] Pulling current alpha-research-v2...'
git pull origin alpha-research-v2

Write-Host '[2/4] Running deterministic semantic alpha search (no LLM, no network)...'
python .\scripts\run_autonomous_v2_discovery.py --count $Count
if ($LASTEXITCODE -ne 0) {
    Write-Host '[3/4] Discovery failed; finalizing sanitized failure state...'
    if ($NoPush) {
        .\scripts\finalize_task.ps1 -Message 'chore: capture failed autonomous v2 discovery' -NoKnowledgeBuild -NoPush
    } else {
        .\scripts\finalize_task.ps1 -Message 'chore: capture failed autonomous v2 discovery' -NoKnowledgeBuild
    }
    exit $LASTEXITCODE
}

Write-Host '[3/4] Finalizing tests and snapshots...'
# Field profiles are already calibrated. Rebuilding them here would overwrite
# manual/LLM semantic corrections, so this workflow only refreshes snapshots.
if ($NoPush) {
    .\scripts\finalize_task.ps1 -Message 'feat: generate autonomous v2 breadth candidates' -NoKnowledgeBuild -NoPush
} else {
    .\scripts\finalize_task.ps1 -Message 'feat: generate autonomous v2 breadth candidates' -NoKnowledgeBuild
}

Write-Host '[4/4] Done. No LLM/API call and no BRAIN simulation were sent.'
