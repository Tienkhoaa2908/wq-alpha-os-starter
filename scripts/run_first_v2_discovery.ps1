param(
    [int]$Count = 6,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'

if ($Count -ne 6) {
    throw 'The first breadth cycle is fixed at exactly 6 hypotheses.'
}

Write-Host '[1/4] Pulling current alpha-research-v2...'
$branch = (git branch --show-current).Trim()
if ($branch -ne 'alpha-research-v2') {
    throw "Current branch is '$branch'. Switch to alpha-research-v2 first."
}
git pull origin alpha-research-v2

Write-Host '[2/4] Running local first-v2 discovery pipeline...'
python .\scripts\run_first_v2_discovery.py --count $Count

Write-Host '[3/4] Finalizing tests, audits and coordination snapshots...'
# Do not rebuild deterministic field profiles here: candidate semantic reviews
# are intentional local corrections and must not be overwritten in this task.
if ($NoPush) {
    .\scripts\finalize_task.ps1 -Message 'feat: run first reviewed v2 discovery' -NoKnowledgeBuild -NoPush
} else {
    .\scripts\finalize_task.ps1 -Message 'feat: run first reviewed v2 discovery' -NoKnowledgeBuild
}

Write-Host '[4/4] Done. No BRAIN simulation was sent by this workflow.'
