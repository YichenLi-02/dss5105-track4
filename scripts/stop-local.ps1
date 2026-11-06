$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $root 'local-data\server.json'
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Output 'No service started by Start-Local.cmd was recorded.'
    return
}
$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
if ($state.status -ne 'running') {
    Write-Output 'The local service is already stopped.'
    return
}
if ($state.project -ne $root) { throw 'State file belongs to a different project. Nothing was stopped.' }
$process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($process) {
    if ($process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$state.started_at).ToUniversalTime().Ticks -or
        $process.Path -ne $state.executable) {
        throw 'The recorded process ID has been reused. Nothing was stopped.'
    }
    # The Windows virtual-environment launcher owns a separate Python child.
    & taskkill.exe /PID "$($process.Id)" /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The local process tree could not be stopped.' }
    Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
}
[ordered]@{status = 'stopped'; project = $root; url = $state.url} |
    ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
Write-Output 'Local service stopped. Saved data was not removed.'
