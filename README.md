# Astra Licensing Automation — Backend

Production backend foundation for Astra Business Services' licensing-mailbox
automation: PostgreSQL data model, FastAPI read API, atomic email
state-machine, and tooling to import the PowerShell prototype's data.

## Current milestone boundary (Milestone 1)

**In scope:** PostgreSQL schema + Alembic migrations, async SQLAlchemy ORM,
read-only operational API, email processing state machine with audit +
transactional outbox, prototype JSON importer, dev seed data, structured
redacted logging, correlation IDs, Docker dev environment, tests, CI.

**Explicitly out of scope (later milestones):** live Microsoft Graph calls,
webhooks, delta sync execution, Outlook draft creation/sending, message
moves, SharePoint, Service Bus publishing, Key Vault, LLM classification,
NMLS automation, the review portal frontend, and production Entra JWT auth.
Nothing in this codebase talks to Microsoft 365, OpenAI, or any external
service.

The proven PowerShell prototype is retained under
`scripts/powershell-acceptance-tests/` as acceptance/recovery tooling; its
runtime data lives in `prototype-data/` (gitignored — contains real Graph
IDs).

## Architecture overview

FastAPI routers → services (transactions, state machine, audit/outbox) →
repositories → async SQLAlchemy → PostgreSQL. See
[docs/architecture.md](docs/architecture.md),
[docs/data-model.md](docs/data-model.md),
[docs/state-machine.md](docs/state-machine.md),
[docs/prototype-import.md](docs/prototype-import.md).

## Requirements

- Python 3.12+ (developed on 3.12/3.13)
- Docker Desktop (PostgreSQL 16 via Compose)
- Windows PowerShell or any POSIX shell

## Setup (Windows)

```powershell
docker compose up -d db          # PostgreSQL on host port 5442

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"

alembic upgrade head             # create schema
python -m app.cli.seed_dev       # optional synthetic dev data

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Or simply: `.\scripts\dev.ps1` (does all of the above).

> The Compose database listens on host port **5442** (not 5432) to avoid
> colliding with a native PostgreSQL service. All defaults and `.env.example`
> already point there.

## Docker (full stack)

```powershell
docker compose up -d             # db + app (app on http://localhost:8000)
```

## Environment variables

Copy `.env.example` to `.env` and adjust. Key settings:

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `local` | `local` / `test` / `staging` / `production` |
| `DATABASE_URL` | `postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing` | PostgreSQL only |
| `AUTH_MODE` | `development` | Rejected at startup when `APP_ENV=production` |
| `LOG_FORMAT` | `json` | `json` or `console`; both redact secrets |
| `PROTOTYPE_IMPORT_ROOT` | `./prototype-data` | Importer default root |

Production startup fails fast on unsafe settings (dev auth, SQL echo,
wildcard CORS). Never commit `.env` or any secret.

## Migrations

```powershell
alembic upgrade head                 # apply
alembic downgrade base               # tear down (dev/test only)
alembic revision --autogenerate -m "..."   # then review the output manually
```

Initial revision: `0001` (`migrations/versions/0001_initial_schema.py`).
A drift test fails CI when models and migrations disagree.

## Running tests

```powershell
docker compose up -d db          # tests use a real PostgreSQL database
pytest                           # full suite
pytest tests/unit -q             # fast, DB-free subset
.\scripts\test.ps1               # format check + lint + mypy + coverage gate
```

Integration tests use `astra_licensing_test` (auto-created; override with
`TEST_DATABASE_URL`).

## Importing the PowerShell prototype

```powershell
python -m app.cli.import_prototype --root .\prototype-data --mailbox astralicensing@astraglobal.com --dry-run
python -m app.cli.import_prototype --root .\prototype-data --mailbox astralicensing@astraglobal.com
```

Idempotent; per-record transactions; machine-readable JSON report on stdout.
Details: [docs/prototype-import.md](docs/prototype-import.md).

## API documentation

Interactive docs: <http://127.0.0.1:8000/docs> (OpenAPI at `/openapi.json`).

Quick checks:

- `GET /health/live`, `GET /health/ready`
- `GET /api/v1/system/version`
- `GET /api/v1/mailboxes`, `GET /api/v1/emails`, `GET /api/v1/tasks`
- `GET /api/v1/audit-events`

## Security notes

- No Microsoft client secret, Graph token, or LLM key exists anywhere in this
  repository; Milestone 1 makes no external calls.
- Logs are structured JSON with enforced redaction (DB credentials, bearer
  tokens, delta links, sensitive keys). Email bodies are never logged and are
  excluded from list endpoints and from detail responses unless
  `include_body=true` is requested.
- Graph delta links are opaque: never returned by the API, never fully
  logged.
- `AUTH_MODE=development` (synthetic actor from a controlled header) is for
  local/test only and is rejected when `APP_ENV=production`. Microsoft Entra
  JWT validation will be added before the portal is exposed to
  organizational users.
- Correlation IDs from clients are accepted only when they are valid UUIDs.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `password authentication failed` on 5432 | Another PostgreSQL owns that port; this project uses **5442**. Check `DATABASE_URL`. |
| `Bind for 0.0.0.0:5442 failed` | Port taken — change the host port in `compose.yaml` and `DATABASE_URL`. |
| `/health/ready` returns 503 | Database not up: `docker compose up -d db`, wait for the healthcheck. |
| Tests fail with `database "astra_licensing_test" does not exist` | It is auto-created; if the DB volume predates the init script, run `docker compose down -v && docker compose up -d db`. |
| `alembic upgrade` cannot connect | Set `DATABASE_URL` in the shell or `.env`; the env var overrides `alembic.ini`. |
| Windows: `Activate.ps1` blocked | `Set-ExecutionPolicy -Scope Process RemoteSigned` |
