param([string]$RuntimeDir = (Join-Path $env:USERPROFILE 'Documents\Codex\wind-agent-runtime'))
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} else {
    $uv = Join-Path $RuntimeDir 'bin\uv.exe'
    if (-not (Test-Path -LiteralPath $uv)) {
        $archive = Join-Path $RuntimeDir 'uv.zip'
        Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.12.18/uv-x86_64-pc-windows-msvc.zip' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $RuntimeDir 'bin') -Force
    }
}
$env:UV_CACHE_DIR = Join-Path $RuntimeDir 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeDir 'python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $RuntimeDir '.venv'
Push-Location $repo
try {
    & $uv sync --python 3.11 --frozen --extra dev --no-editable
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    $python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
    @{python=$python; runtime=$RuntimeDir; uv=$uv} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repo '.runtime.json') -Encoding utf8
    & $python -X utf8 -m wind_agent doctor
    if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed' }
    Write-Host 'Ready. Run scripts/run.ps1 run-all, then scripts/start.ps1.'
} finally { Pop-Location }
