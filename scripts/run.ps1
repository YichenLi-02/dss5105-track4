# One-command local start: install deps if missing, build the frontend, serve everything on :8000.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$be = Join-Path $root 'src\backend'
$fe = Join-Path $root 'src\frontend'
if (-not (Test-Path (Join-Path $be '.venv'))) {
    python -m venv (Join-Path $be '.venv')
    & (Join-Path $be '.venv\Scripts\python.exe') -m pip install -r (Join-Path $be 'requirements-dev.txt')
}
if (-not (Test-Path (Join-Path $fe 'node_modules'))) { Push-Location $fe; npm ci; Pop-Location }
Push-Location $fe; npm run build; Pop-Location
Push-Location $be
& (Join-Path $be '.venv\Scripts\python.exe') -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location
