# Local development bootstrap: database, venv, migrations, seed, API server.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& .\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

python -m app.cli.seed_dev
if ($LASTEXITCODE -ne 0) { throw "seed failed" }

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
