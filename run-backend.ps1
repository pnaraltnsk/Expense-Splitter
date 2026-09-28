$ErrorActionPreference = 'Stop'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv was not found on PATH. Install uv, reopen PowerShell, and try again.'
    exit 1
}

$backendPath = Join-Path $PSScriptRoot 'backend'
uv --directory $backendPath sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv --directory $backendPath run uvicorn app.main:app --reload
exit $LASTEXITCODE
