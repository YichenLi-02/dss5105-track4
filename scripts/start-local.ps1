param(
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'src\backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$index = Join-Path $root 'src\frontend\dist\index.html'
$data = Join-Path $root 'local-data'
$logs = Join-Path $data 'logs'
$stateFile = Join-Path $data 'server.json'
$url = "http://127.0.0.1:$Port"

if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment missing. Follow README.md to install dependencies.' }
if (-not (Test-Path -LiteralPath $index)) { throw 'Frontend build missing. Run npm run build in src/frontend.' }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if (Test-Path -LiteralPath $stateFile) {
    $state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
    if ($state.status -eq 'running') {
        $existing = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if ($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq ([datetime]$state.started_at).ToUniversalTime().Ticks) {
            $health = Invoke-RestMethod -Uri "$($state.url)/api/health" -TimeoutSec 3
            if ($health.status -ne 'ok') { throw 'Existing process did not pass its health check.' }
            Write-Output "Already running: $($state.url)"
            if ($OpenBrowser) { Start-Process $state.url }
            return
        }
    }
}

$probe = New-Object Net.Sockets.TcpClient
try {
    $pending = $probe.ConnectAsync('127.0.0.1', $Port)
    try { [void]$pending.Wait(400) } catch { }
    if ($probe.Connected) { throw "Port $Port is already used by another process. No existing service was stopped." }
}
finally { $probe.Dispose() }

$process = Start-Process -FilePath $python -ArgumentList @(
    '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port"
) -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $logs 'backend.stdout.log') `
  -RedirectStandardError (Join-Path $logs 'backend.stderr.log')

$startedAt = $process.StartTime.ToUniversalTime().ToString('o')
$ready = $false
for ($attempt = 0; $attempt -lt 50; $attempt++) {
    $process.Refresh()
    if ($process.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok') { $ready = $true; break }
    }
    catch { }
    Start-Sleep -Milliseconds 400
}

if (-not $ready) {
    $process.Refresh()
    if (-not $process.HasExited) { & taskkill.exe /PID "$($process.Id)" /T /F | Out-Null }
    throw 'Startup failed. Check local-data/logs/backend.stderr.log.'
}

[ordered]@{
    status = 'running'
    pid = $process.Id
    started_at = $startedAt
    executable = $process.Path
    project = $root
    url = $url
} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

Write-Output "Running: $url"
Write-Output "Process ID: $($process.Id). Mode: $($health.mode)."
Write-Output 'Logs: local-data/logs. Use Stop-Local.cmd to stop only this service.'
if ($health.mode -eq 'live') {
    Write-Output 'Live mode requires the local session code shown in local-data/logs/backend.stdout.log.'
    Write-Output 'The code changes after a restart. Enter it only on this local application; do not share the log.'
}
if ($OpenBrowser) { Start-Process $url }
