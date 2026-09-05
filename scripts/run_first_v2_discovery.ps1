param(
    [int]$Count = 6,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'

function Assert-NativeSuccess {
    param(
        [string]$Step
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

if ($Count -ne 6) {
    throw 'The first breadth cycle is fixed at exactly 6 hypotheses.'
}

Write-Host '[1/4] Pulling current alpha-research-v2...'
$branch = (git branch --show-current).Trim()
if ($branch -ne 'alpha-research-v2') {
    throw "Current branch is '$branch'. Switch to alpha-research-v2 first."
}
git pull origin alpha-research-v2
Assert-NativeSuccess 'git pull'

Write-Host '[2/4] Running local first-v2 discovery pipeline...'
python .\scripts\run_first_v2_discovery.py --count $Count
$pipelineExit = $LASTEXITCODE

if ($pipelineExit -ne 0) {
    Write-Host "First-v2 discovery failed with exit code $pipelineExit. Publishing sanitized failure status..."
    if ($NoPush) {
        .\scripts\finalize_task.ps1 -Message 'chore: capture failed first v2 discovery' -NoKnowledgeBuild -NoPush
    } else {
        .\scripts\finalize_task.ps1 -Message 'chore: capture failed first v2 discovery' -NoKnowledgeBuild
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Failure-status finalization also returned a non-zero exit code.'
    }
    exit $pipelineExit
}

Write-Host '[3/4] Finalizing tests, audits and coordination snapshots...'
# Do not rebuild deterministic field profiles here: candidate semantic reviews
# are intentional local corrections and must not be overwritten in this task.
if ($NoPush) {
    .\scripts\finalize_task.ps1 -Message 'feat: run first reviewed v2 discovery' -NoKnowledgeBuild -NoPush
} else {
    .\scripts\finalize_task.ps1 -Message 'feat: run first reviewed v2 discovery' -NoKnowledgeBuild
}
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host '[4/4] Done. No BRAIN simulation was sent by this workflow.'
