$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$runtimeFile = Join-Path $repo '.runtime.json'
if (Test-Path -LiteralPath $runtimeFile) {
    $python = (Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json).python
} else {
    $python = Join-Path $env:USERPROFILE 'Documents\Codex\wind-agent-runtime\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 first' }
Push-Location $repo
try {
    & $python -X utf8 -m wind_agent @args
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
