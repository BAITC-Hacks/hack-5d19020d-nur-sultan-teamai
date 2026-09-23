$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$runtime = Get-Content -LiteralPath (Join-Path $repo '.runtime.json') -Raw | ConvertFrom-Json
$servicePath = Join-Path $runtime.runtime 'services.json'
if (-not (Test-Path -LiteralPath $servicePath)) { return }
$services = Get-Content -LiteralPath $servicePath -Raw | ConvertFrom-Json
foreach ($service in $services) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($service.pid)" -ErrorAction SilentlyContinue
    if ($process -and $process.ExecutablePath -eq $service.executable -and $process.CommandLine -match '(wind_agent|streamlit)') {
        Stop-Process -Id $service.pid
        Write-Host "Stopped $($service.name)"
    }
}
Remove-Item -LiteralPath $servicePath
