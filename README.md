# Astra Licensing Automation — Backend

Production backend foundation for Astra Business Services' licensing-mailbox
automation: PostgreSQL data model, FastAPI read API, atomic email
state-machine, and tooling to import the PowerShell prototype's data.

## Deployment (Milestone 8)

Milestone 8 makes the system deployable and operable: Railway service
definitions for the backend, portal, general worker, cron scheduler, browser
worker, and PostgreSQL; separated staging and production environments;
Alembic migrations as a pre-deploy gate; an operations status endpoint; and
the migration, UAT, pilot, and go-live procedures.

- [DEPLOYMENT.md](DEPLOYMENT.md) — Railway layout, variables, migrations,
  backups, restore, rollback, common failures, security checklist
- [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) — migration, reconciliation,
  UAT, pilot, approvals, go-live sequence, contacts
- [production data migration](docs/production-data-migration.md) ·
  [UAT checklist](docs/uat-checklist.md) ·
  [pilot checklist](docs/pilot-checklist.md) ·
  [staging acceptance](docs/milestone8-staging-acceptance.md)

```powershell
python -m app.cli.check_deployment          # pre-deploy configuration gate
alembic upgrade head                        # pre-deploy migration
python -m app.cli.migration_reconcile check --expected expected-counts.json
```

Operational endpoints: `GET /health/live`, `GET /health/ready`,
`GET /api/v1/operations/status`, `GET /metrics`.

Autonomous filing is not enabled by any configuration: human review, send
approval, and human final submission remain mandatory.

## Milestone 5 boundary

Milestone 5 adds controlled response plans, immutable local and Graph draft
revisions, governed attachments, separate exact-snapshot send approval,
durable send/Sent Items reconciliation, verified source routing, and atomic
email-workflow completion. Graph draft, send, move, reply-all, BCC, and large
attachment features remain gated for staging acceptance.

**Milestone 1** delivered the PostgreSQL schema, read API, state machine with
audit + transactional outbox, prototype importer, and CI.

**Milestone 2** adds the production Microsoft Graph ingestion boundary:
app-only MSAL authentication, a resilient async Graph client, Outlook message
subscriptions (create/renew/reconcile), webhook + lifecycle receivers with
clientState validation, durable notification receipts, a PostgreSQL-backed
job queue with leases and coalescing, Inbox delta synchronization, email
evidence capture (full JSON + raw MIME + attachments with SHA-256), workers,
a scheduler, Prometheus metrics, and operational CLI/API. Processing stops at
`ATTACHMENTS_SAVED`.

**Explicitly out of scope:** autonomous regulator/NMLS filing, license
inventory and renewal engines, and autonomous delivery claims. Automated
tests use mocked provider calls only; CI blackholes Microsoft Graph, Entra
login, and OpenAI hostnames and never sends an email.

### Graph documentation

[graph-integration](docs/graph-integration.md) ·
[webhook-security](docs/webhook-security.md) ·
[delta-synchronization](docs/delta-synchronization.md) ·
[operations runbook](docs/graph-operations-runbook.md) ·
[staging acceptance](docs/staging-acceptance.md)

Milestone 5 operations: [response drafting](docs/response-drafting.md) ·
[send approval](docs/send-approval-workflow.md) ·
[Graph draft and send](docs/graph-draft-and-send.md) ·
[communications runbook](docs/communications-operations-runbook.md) ·
[staging acceptance](docs/milestone5-staging-acceptance.md)

### Running the workers

```powershell
# One general worker (the deployed topology): one claim loop per queue family.
python -m app.workers.runner --queues graph,ingestion,classification,documents,communications,licensing,requirements,deadlines,packets,forms,imports

# Or split them when load justifies it.
python -m app.workers.runner --queues subscriptions,sync,ingestion
python -m app.workers.runner --queues communications
python -m app.workers.runner --queues licensing,requirements,deadlines,packets,forms,imports

python -m app.workers.scheduler --once    # cron: enqueue durable jobs and exit
python -m app.workers.scheduling          # single-replica periodic scheduler loop
```

Milestone 6 operations: [license inventory](docs/license-inventory.md) ·
[requirement matrix](docs/requirement-matrix.md) ·
[case workflow](docs/compliance-case-workflow.md) ·
[deadline engine](docs/deadline-engine.md) ·
[information registry](docs/reusable-information-registry.md) ·
[packet generation](docs/document-packet-generation.md) ·
[form preparation](docs/form-preparation.md) ·
[tracker migration](docs/master-tracker-migration.md) ·
[operations runbook](docs/licensing-operations-runbook.md) ·
[staging acceptance](docs/milestone6-staging-acceptance.md).

Milestone 7 adds governed, human-supervised portal assistance. It uses
versioned locator contracts, operator-bound ephemeral Playwright sessions,
exact pre-submission snapshots, dedicated human handoffs, and evidence-gated
case transitions. It never stores portal credentials, bypasses MFA or CAPTCHA,
automates legal or payment actions, or submits a filing.

Milestone 7 operations: [governance](docs/portal-automation-governance.md) ·
[session security](docs/browser-session-security.md) ·
[adapter development](docs/portal-adapter-development.md) ·
[NMLS assisted workflow](docs/nmls-assisted-workflow.md) ·
[human handoffs](docs/human-handoff-workflow.md) ·
[pre-submission verification](docs/pre-submission-verification.md) ·
[submission evidence](docs/submission-evidence.md) ·
[operations runbook](docs/portal-operations-runbook.md) ·
[staging acceptance](docs/milestone7-staging-acceptance.md).

Run the isolated browser worker only after portal governance is configured:

```powershell
python -m app.workers.runner --queues portals
python -m app.cli.portal_diagnostics list
```

### Webhook paths

- `POST /webhooks/microsoft-graph/messages`
- `POST /webhooks/microsoft-graph/lifecycle`

Local validation check (no Graph needed):

```powershell
curl.exe -X POST "http://127.0.0.1:8000/webhooks/microsoft-graph/messages?validationToken=milestone2-test"
# -> 200, text/plain, body: milestone2-test
```

Local mock-notification workflow: seed a synthetic subscription and post a
synthetic notification exactly as the test suite does — see
`tests/api/webhooks/test_webhook_api.py` and
`tests/fixtures/graph_payloads.py` (no real identifiers required). Live
subscription validation requires a publicly reachable HTTPS `PUBLIC_BASE_URL`
(see the staging runbook; no specific tunnel vendor is mandated).

### Graph security warnings

- `GRAPH_CLIENT_SECRET` and access tokens never appear in logs, the DB, or
  CLI output; delta links are stored opaquely and only fingerprints are
  logged.
- Webhook notifications are authenticated via hashed clientState with
  constant-time comparison; payloads are treated as signals, never as mail
  content.
- Mutating Graph endpoints are disabled when `APP_ENV=production` until the
  Entra actor layer lands; the filesystem evidence store is likewise rejected
  in production.

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
- `GET /api/v1/documents`, `GET /api/v1/documents/{id}`
- `GET /api/v1/integrations/sharepoint/status`, `/drives`, `/jobs`

## Milestone 3: SharePoint document repository

Milestone 3 adds migration `0003_sharepoint_documents`, the governed document/version/link/event catalog, a `Sites.Selected` SharePoint client, simple and resumable uploads, metadata-column synchronization, attachment promotion, exact-hash deduplication, approval/reuse lifecycle, controlled downloads/previews, delta reconciliation, evidence migration, and leased document jobs.

SharePoint remains disabled by default. Configure IDs using [docs/sharepoint-permissions.md](docs/sharepoint-permissions.md), run the non-destructive bootstrap in [docs/sharepoint-operations-runbook.md](docs/sharepoint-operations-runbook.md), and execute [docs/milestone3-staging-acceptance.md](docs/milestone3-staging-acceptance.md) with synthetic files only.

## Milestone 4: classification, review portal, and tasks

Migration `0004_classification_review` adds Entra user/role observations, the vendor registry, immutable rule/prompt/run records, review claims and field corrections, and task comments/events. Classification is deterministic-first; optional OpenAI Responses enrichment is disabled by default and gated by explicit approval/data-policy settings. Every initial result requires human review.

```powershell
alembic upgrade head
uvicorn app.main:app --reload
python -m app.workers.runner --queues classification
cd frontend
npm ci
npm run dev
```

The portal is at <http://127.0.0.1:5173>. Local/test synthetic actor mode is replaced by MSAL authorization-code + PKCE when the `VITE_ENTRA_*` variables are configured. See [Entra setup](docs/entra-user-authentication.md), [classification architecture](docs/classification-architecture.md), [review workflow](docs/human-review-workflow.md), [task workflow](docs/task-workflow.md), and [staging acceptance](docs/milestone4-staging-acceptance.md).

## Security notes

- No Microsoft client secret, Graph token, or model-provider key exists in this repository. CI blocks live Microsoft/OpenAI hosts and uses mocks.
- Logs are structured JSON with enforced redaction (DB credentials, bearer
  tokens, delta links, sensitive keys). Email bodies are never logged and are
  excluded from list endpoints and from detail responses unless
  `include_body=true` is requested.
- Graph delta links are opaque: never returned by the API, never fully
  logged.
- `AUTH_MODE=development` is local/test only. Entra mode validates signature, issuer, single tenant, backend audience, time claims, and API scope/roles before backend authorization.
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
| Many tests error with `PermissionError: [WinError 5] ... Temp\pytest-of-<user>` | That temp directory's permissions are broken (even reading its ACL fails). Point pytest elsewhere: `setx PYTEST_DEBUG_TEMPROOT C:\Users\<user>\pytest-temp`, then open a new shell. To delete the broken directory instead, run an **elevated** shell: `takeown /f "%TEMP%\pytest-of-%USERNAME%" /r /d y` then `rmdir /s /q "%TEMP%\pytest-of-%USERNAME%"`. |
