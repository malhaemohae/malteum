param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
$pythonPath = Join-Path $RepoRoot "rulepack\.venv\Scripts\python.exe"
$regwatchRoot = Join-Path $RepoRoot "regwatch"
$sourceRoot = Join-Path $regwatchRoot "src"
$configPath = Join-Path $regwatchRoot "config\sources.json"
$statePath = Join-Path $regwatchRoot "var\state.json"
$reportPath = Join-Path $regwatchRoot "var\latest-report.json"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python 실행 파일을 찾지 못함: $pythonPath"
}

$env:PYTHONPATH = $sourceRoot
& $pythonPath -m regwatch.cli run --config $configPath --state $statePath --report $reportPath
exit $LASTEXITCODE
