$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment' }
    & $python -m pip install -r backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install backend dependencies' }
}
if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) {
    Copy-Item -LiteralPath (Join-Path $root '.env.example') -Destination (Join-Path $root '.env')
    Write-Host 'Created .env. Set credentials, or enable local login with a strong DEV_LOGIN_KEY.'
}
# One application worker is intentional: the durable SQLite queue has one scheduler.
& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
