param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$settings = Join-Path $repo '.runtime.json'
if (-not (Test-Path -LiteralPath $settings)) { throw 'Run scripts/setup.ps1 first' }
$runtime = Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json
$logs = Join-Path $runtime.runtime 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$servicePath = Join-Path $runtime.runtime 'services.json'
if (Test-Path -LiteralPath $servicePath) {
    $old = Get-Content -LiteralPath $servicePath -Raw | ConvertFrom-Json
    $live = @($old | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue })
    if ($live.Count -gt 0) {
        Write-Host 'Services are already running. Use scripts/stop.ps1 before restarting.'
        return
    }
}
$services = @()
foreach ($entry in @(
    @{name='api'; command=@('-X','utf8','-m','wind_agent','serve')},
    @{name='worker'; command=@('-X','utf8','-m','wind_agent','worker')},
    @{name='ui'; command=@('-X','utf8','-m','streamlit','run','ui/app.py')}
)) {
    $process = Start-Process -FilePath $runtime.python -ArgumentList $entry.command -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs ($entry.name+'.out.log')) -RedirectStandardError (Join-Path $logs ($entry.name+'.err.log'))
    $services += @{name=$entry.name; pid=$process.Id; executable=$runtime.python}
}
$services | ConvertTo-Json | Set-Content -LiteralPath $servicePath -Encoding utf8
Write-Host 'UI: http://127.0.0.1:8501'
Write-Host 'API: http://127.0.0.1:8000/docs'
Write-Host "Logs: $logs"
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8501' }
