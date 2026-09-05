param(
    [Parameter(Mandatory=$true)]
    [string]$Message,
    [switch]$NoKnowledgeBuild,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'

Write-Host '[1/6] Running tests...'
python -m unittest discover -s tests -v

if (-not $NoKnowledgeBuild) {
    Write-Host '[2/6] Rebuilding deterministic research knowledge...'
    alpha-os knowledge build
} else {
    Write-Host '[2/6] Skipping knowledge build by request.'
}

Write-Host '[3/6] Exporting sanitized coordination snapshot...'
python .\scripts\export_research_state.py

Write-Host '[4/6] Staging source-controlled project state...'
$paths = @(
    '.github',
    'src',
    'tests',
    'scripts',
    'config',
    'docs',
    'README.md',
    'AGENTS.md',
    '00_TONG_QUAN_DU_AN.md',
    'pyproject.toml',
    '.gitignore',
    '.env.example'
)
foreach ($path in $paths) {
    if (Test-Path $path) {
        git add -- $path
    }
}

git diff --cached --check
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host 'No staged changes. Nothing to commit.'
    exit 0
}

Write-Host '[5/6] Files staged:'
$staged | ForEach-Object { Write-Host " - $_" }

git commit -m $Message

if ($NoPush) {
    Write-Host '[6/6] Commit created; push skipped by request.'
} else {
    $branch = (git branch --show-current).Trim()
    if (-not $branch) {
        throw 'Cannot determine current Git branch.'
    }
    Write-Host "[6/6] Pushing branch $branch..."
    git push origin $branch
}

Write-Host 'Task finalized. GitHub now contains code + current coordination snapshot.'
