# Quality gate: format check, lint, types, tests with coverage.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

& .\.venv\Scripts\Activate.ps1

ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "ruff format check failed" }

ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff lint failed" }

mypy app
if ($LASTEXITCODE -ne 0) { throw "mypy failed" }

pytest --cov=app --cov-fail-under=85
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

Write-Host "All quality gates passed." -ForegroundColor Green
