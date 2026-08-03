# Deployment (Railway)

Operating guide for the Astra licensing automation system on Railway. It covers
the project layout, both environments, variables, migrations, workers, cron,
health checks, backups, restore, rollback, and the production checklist.

Everything here uses Railway's own deployment, logs, variables, health checks,
backups, and deployment history. No additional infrastructure, orchestration,
or observability platform is introduced.

For the concise source, ownership, live-link, and service map, see
[`docs/deployment-reference.md`](docs/deployment-reference.md).

---

## 1. Project layout

One Railway project, two environments (`staging`, `production`), five services
plus the database in each environment.

| Service | Source | Command | Public |
| --- | --- | --- | --- |
| `backend` | repo root, `Dockerfile` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | `api.<approved-domain>` |
| `frontend` | `frontend/`, `frontend/Dockerfile` | nginx (image default) | `licensing.<approved-domain>` |
| `worker` | repo root, `Dockerfile` | `python -m app.workers.runner --queues graph,ingestion,classification,documents,communications,licensing,requirements,deadlines,packets,forms,imports` | no |
| `scheduler` | repo root, `Dockerfile` | `python -m app.workers.scheduler --once` (cron `*/5 * * * *`) | no |
| `browser-worker` | repo root, `Dockerfile.browser` | `python -m app.workers.runner --queues portals` | no |
| `Postgres` | Railway plugin | — | no |

Deployed staging environment (project `astra-licensing`):
`https://backend-staging-2030.up.railway.app` ·
`https://frontend-staging-7f87.up.railway.app`

Two service settings are not expressible in the per-service JSON and are set on
the service itself (dashboard, or `serviceInstanceUpdate` via `railway api`):
`railwayConfigFile` — which `railway*.json` the service reads — and
`rootDirectory`, which the frontend sets to `frontend`. Without the first, every
service deployed from this repo inherits the backend's start command and health
check.

`backend` is the only service that exposes application APIs. The
`browser-worker` is deployed **only** when portal assistance is approved and
enabled.

Config-as-code files, one per service (set each service's *Config as code* path
in Railway):

- `railway.json` — backend
- `railway.worker.json` — worker
- `railway.scheduler.json` — scheduler (includes `cronSchedule`)
- `railway.browser-worker.json` — browser worker
- `frontend/railway.json` — frontend (service root directory `frontend`)

Each file sets watch patterns, so a frontend-only change does not rebuild the
backend services and vice versa.

Commands in these files are executed **without a shell**, so anything relying
on shell behaviour — `$PORT` expansion, `&&` chaining — is wrapped in
`sh -c '…'`. An unwrapped `--port $PORT` reaches uvicorn as the literal string
and the container never binds a port, which surfaces only as a failed health
check.

---

## 2. Creating the project

Install and authenticate the CLI (`railway login` opens a browser;
`railway login --browserless` prints a pairing code for headless machines):

```bash
npm install -g @railway/cli
```

```bash
railway login
```

Then, from the repository root (CLI flags vary between versions — confirm with
`railway --help` if a command is rejected):

```bash
railway init --name astra-licensing
```

```bash
railway add --database postgres
```

Create the services (repeat per environment; `railway environment` switches):

```bash
railway add --service backend && railway add --service frontend && railway add --service worker && railway add --service scheduler
```

In the Railway dashboard, for each service set:

1. **Source** — this GitHub repository and branch.
2. **Root directory** — repository root, except `frontend` which uses `frontend`.
3. **Config as code** — the `railway*.json` path from the table above.
4. **Variables** — see section 4.
5. **Networking** — a public domain for `backend` and `frontend` only.

Create the second environment by duplicating the first:

```bash
railway environment new production --duplicate staging
```

Then replace every staging value: database reference, domains, Entra redirect
URIs, Graph credentials, mailbox, SharePoint site, model key, allowed
recipients, and feature flags. **A staging service must never point at the
production database, mailbox, SharePoint site, or portal account.**

---

## 3. Environments

| | staging | production |
| --- | --- | --- |
| Purpose | Graph/SharePoint testing, send tests to approved internal recipients, migration dry runs, portal fixtures, UAT | real licensing work |
| `APP_ENV` | `staging` | `production` |
| Data | synthetic or copied-and-scrubbed | live |
| Send | internal recipients only | enabled after send-approval testing |
| Portal | synthetic/approved test portal | approved portals only |

Production is enabled only after staging acceptance
(`docs/milestone8-staging-acceptance.md`) and the go-live checklist
(`GO_LIVE_CHECKLIST.md`).

---

## 4. Variables

Copy `deploy/railway/backend.env.example` into the Railway raw variable editor
for `backend`, `worker`, `scheduler`, and `browser-worker`; copy
`deploy/railway/frontend.env.example` for `frontend`. `.env.example` documents
every remaining setting with its default.

Database connections use a Railway reference variable, never a literal string:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

### Minimum per service

**Application:** `APP_ENV`, `APP_VERSION`, `LOG_LEVEL`, `DATABASE_URL`,
`FRONTEND_URL`, `BACKEND_URL`, `CORS_ORIGINS`.

**Authentication:** `AUTH_MODE=entra`, `ENTRA_TENANT_ID`,
`ENTRA_API_CLIENT_ID`, `ENTRA_API_AUDIENCE`, `ENTRA_API_SCOPE`.

**Graph:** `GRAPH_ENABLED`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`,
`GRAPH_CLIENT_SECRET` (or `GRAPH_CREDENTIAL_MODE=certificate` with
`GRAPH_CERTIFICATE_PATH` and `GRAPH_CERTIFICATE_THUMBPRINT`), `GRAPH_MAILBOX`,
`PUBLIC_BASE_URL`.

**SharePoint:** `SHAREPOINT_ENABLED`, `SHAREPOINT_SITE_ID`,
`SHAREPOINT_EXPECTED_APP_ID`, and every `SHAREPOINT_*_DRIVE_ID`.

**Document storage:** `EVIDENCE_STORAGE_BACKEND` selects where document content
is written — `sharepoint` (repository of record) or `r2` (Cloudflare fallback,
bucket `astra-licensing-documents`). R2 additionally needs `R2_ACCOUNT_ID`,
`R2_BUCKET`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` on every service
that writes evidence. See [docs/r2-document-storage.md](docs/r2-document-storage.md).

**Classification:** `CLASSIFICATION_ENABLED`, `AI_CLASSIFICATION_ENABLED`,
`OPENAI_API_KEY` and `OPENAI_MODEL` (only once external-provider use is
approved).

**Communications:** `GRAPH_DRAFT_CREATION_ENABLED`, `GRAPH_SEND_ENABLED`,
`GRAPH_MESSAGE_MOVE_ENABLED`, `COMMUNICATION_REQUIRE_SEND_APPROVAL=true`.

**Portal assistance:** `PORTAL_AUTOMATION_ENABLED`,
`BROWSER_AUTOMATION_ENABLED`, `PORTAL_ALLOWED_HOSTS`, and the
`PORTAL_*_HUMAN_ONLY` flags (all `true`).

**Frontend:** `VITE_API_BASE_URL`, `VITE_ENTRA_TENANT_ID`,
`VITE_ENTRA_SPA_CLIENT_ID`, `VITE_ENTRA_API_SCOPE`, `VITE_APP_ENV`. Railway
passes these to the Docker build, where Vite inlines them.

### Never in frontend variables

`GRAPH_CLIENT_SECRET`, `OPENAI_API_KEY`, `DATABASE_URL`, any SharePoint secret,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`BROWSER_SESSION_ENCRYPTION_KEY_REFERENCE`. They would be published in the
public bundle.

### Verifying variables

```bash
python -m app.cli.check_deployment
```

Runs as part of the backend pre-deploy command. It loads the environment
exactly as the application does, prints a JSON report, and exits non-zero when
a variable is missing or unsafe. It never prints a secret value.

---

## 5. Domains

- `backend` → `api.<approved-domain>`; also set `PUBLIC_BASE_URL` to the same
  address, because Graph subscription validation calls it.
- `frontend` → `licensing.<approved-domain>`; set `VITE_API_BASE_URL` to
  `https://api.<approved-domain>/api/v1` and add the frontend origin to
  `CORS_ORIGINS`.
- Register both the frontend origin and its `/` redirect URI on the Entra SPA
  app registration. The full sign-in setup — scope, app roles, role
  assignment, and the variables on each service — is in
  [docs/entra-sign-in.md](docs/entra-sign-in.md).

Workers, the scheduler, and the browser worker have no domain and reach the
database over Railway's private network.

---

## 6. Database and migrations

Railway PostgreSQL is provisioned once per environment and referenced by every
service. It is not exposed publicly; use `railway connect Postgres` for
temporary administration.

Migrations run as the backend's **pre-deploy** command, so a failed migration
fails the deployment and the previous version keeps serving:

```
python -m app.cli.check_deployment --compact && alembic upgrade head
```

Manual run against an environment:

```bash
railway run --service backend alembic upgrade head
```

Migration facts worth knowing:

- Revisions `0001`–`0007` cover Milestones 1–7 and are applied in order.
- `alembic upgrade head` is a no-op when already at head, so every redeploy is
  safe.
- The Alembic version column is widened to 64 characters
  (`migrations/env.py`); revision identifiers longer than 32 characters
  otherwise fail only at the end of a clean-database run.

---

## 7. Workers, scheduler, and browser worker

The general `worker` runs one claim loop per queue family in a single process.
Split queues into separate Railway services only if real load justifies it.

The `scheduler` is a Railway **cron** service running `--once` every five
minutes. Each run enqueues durable jobs and exits; it never performs business
processing itself:

- Graph subscription maintenance
- Inbox reconciliation sync
- deadline materialization
- document-expiry checks
- stale-information checks
- abandoned-lease recovery (graph, licensing, document, portal queues)
- portal review/authorization expiry and browser-session cleanup

Concurrent scheduler runs are safe: a PostgreSQL advisory lock allows one at a
time, and enqueue keys are time-bucketed for idempotency.

The `browser-worker` uses the Playwright image, has no public domain, keeps
browser files in `/tmp/astra-portals` for the session only, uploads retained
evidence to the governed document store, and stores no portal password, MFA
code, cookie, or profile.

---

## 8. Health checks and logs

- `GET /health/live` — process is up.
- `GET /health/ready` — database reachable; configured as the Railway health
  check path, so a deployment that cannot reach PostgreSQL never receives
  traffic.
- `GET /api/v1/operations/status` — API and database status, last Inbox sync,
  pending and failed-review jobs per queue, last scheduler run, worker
  heartbeats, Graph subscription status, SharePoint status, the mandatory
  control flags, and a short `alerts` list. No secret or delta link appears in
  the response.
- `GET /metrics` — Prometheus metrics (unchanged from earlier milestones).
- `GET /healthz` on the frontend service — nginx static check.

Logs are structured JSON with enforced redaction and correlation IDs. Use
Railway's deployment and service logs; filter by `correlation_id` to follow one
request across services.

Alerts worth acting on immediately (surfaced by `alerts` in the status
endpoint, and by Railway's own deployment/crash notifications):

| Alert | Meaning | First action |
| --- | --- | --- |
| `DATABASE_UNAVAILABLE` | API cannot reach PostgreSQL | check the Postgres service and `DATABASE_URL` |
| `DATABASE_SCHEMA_UNAVAILABLE` | database reachable, tables missing | run `alembic upgrade head` (normally the pre-deploy command) |
| `WORKER_NOT_RUNNING` | no worker heartbeat | check the `worker` service logs and restart |
| `SCHEDULER_NOT_RUNNING` | cron has not run recently | check the cron service history |
| `GRAPH_SYNC_STOPPED` | Inbox sync stalled | check Graph credentials and subscription status |
| `SEND_OUTCOME_AMBIGUOUS` | a send needs manual reconciliation | run `python -m app.cli.send_reconcile` and follow `docs/ambiguous-send-recovery.md` |
| `STATUTORY_DEADLINE_OVERDUE` | a compliance deadline passed | escalate to the responsible owner |
| `REPEATED_FAILED_REVIEW_JOBS` | jobs stuck awaiting review | inspect the queue and clear the cause |

Railway also emails deployment failures and crash restarts; enable those
notifications for the project. Backup failures are reported by Railway on the
database service — check them weekly.

---

## 9. Backups and restore

Enable **scheduled backups** on the Railway Postgres service in both
environments (daily is sufficient; retention per policy).

> Volume backups are a paid Railway capability. On the current account the API
> returns *Not Authorized* for `volumeInstanceBackupScheduleUpdate`, and the
> staging database therefore has **no backup schedule**. Enable it in the
> database service's *Backups* tab (upgrading the plan if prompted) before any
> real licensing data is loaded — a migration with no backup has no rollback.

Restore test — perform once before go-live and after any major schema change:

1. Take (or pick) a backup in the Railway database service.
2. Restore it into a **new** database service in the staging environment.
3. Point a temporary staging backend at the restored database
   (`DATABASE_URL` override) and deploy.
4. Confirm `/health/ready` returns 200 and
   `GET /api/v1/system/version` reports the expected migration revision.
5. Run `python -m app.cli.migration_reconcile totals` and compare with the
   totals recorded at backup time.
6. Remove the temporary service and restore the original `DATABASE_URL`.

Recovering production:

1. Disable processing flags (section 11) and stop `worker`, `scheduler`, and
   `browser-worker`.
2. Restore the backup into the production database service.
3. Run `alembic upgrade head` (redeploying `backend` does this).
4. Verify `/health/ready`, `/api/v1/operations/status`, and reconciliation
   totals.
5. Re-enable services in the go-live order.

---

## 10. Deploying

1. Merge to the deployment branch (or `railway up` from a clean checkout).
2. Railway builds the changed services only (watch patterns).
3. Backend pre-deploy runs the configuration check and `alembic upgrade head`.
4. Railway waits for `/health/ready` before shifting traffic.
5. Confirm `GET /api/v1/operations/status` shows a fresh worker heartbeat and
   a recent scheduler run.

The deployment fails — by design — when the configuration check fails, a
migration fails, readiness never passes, or the frontend build fails.

---

## 11. Rollback

1. Disable processing flags on `backend` and `worker`:
   `GRAPH_SEND_ENABLED=false`, `GRAPH_DRAFT_CREATION_ENABLED=false`,
   `GRAPH_MESSAGE_MOVE_ENABLED=false`, `CLASSIFICATION_AUTO_ENQUEUE=false`,
   `PORTAL_AUTOMATION_ENABLED=false`, `BROWSER_AUTOMATION_ENABLED=false`.
2. Stop `worker`, `scheduler`, and `browser-worker` (Railway → service →
   *Remove*/*Pause*). The portal stays available read-only, which is often
   useful during an incident.
3. Redeploy the last known-good deployment from Railway's deployment history
   (*Deployments → ⋯ → Redeploy*).
4. Restore the database **only** when data is wrong, following section 9.
5. Resume the manual tracker process and tell the licensing team explicitly.
6. Record what happened, then re-enable services in the go-live order.

Migrations are forward-only in practice: prefer redeploying the previous image
with the current schema over `alembic downgrade` in production.

---

## 12. Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Deployment stops at pre-deploy | missing/unsafe variable | read the JSON from `check_deployment` in the build log |
| `value too long for type character varying(32)` | Alembic version column too narrow | already fixed via `version_table_column_length`; recreate the version table if an old database predates it |
| Health check never passes | database unreachable or `DATABASE_URL` literal instead of a reference | use `${{Postgres.DATABASE_URL}}` |
| Portal loads, API calls fail with CORS errors | `CORS_ORIGINS` missing the frontend origin | add the exact origin, no wildcard |
| Portal calls the wrong host | `VITE_API_BASE_URL` unset at **build** time | set the variable, then redeploy so the bundle is rebuilt |
| `Development actor mode is disabled` | `AUTH_MODE=development` outside local/test | set `AUTH_MODE=entra` |
| Graph subscription creation fails | `PUBLIC_BASE_URL` not the public HTTPS backend domain | correct it and re-run subscription maintenance |
| No worker heartbeat | worker service crashed or not deployed | check service logs, restart |
| Jobs stay `PENDING` | worker not running the right queues | check the `--queues` list |
| Browser worker idles | `BROWSER_AUTOMATION_ENABLED=false` | intentional unless portal assistance is approved |

---

## 13. Security checklist

Confirm before each environment goes live, and re-confirm after any variable
change:

- [ ] Production uses `AUTH_MODE=entra`; development actor mode is impossible.
- [ ] The backend validates tenant, audience, scope, and roles on every token.
- [ ] Role restrictions behave as documented in
      `docs/role-and-permission-model.md`.
- [ ] Graph application permissions are scoped to the licensing mailbox only.
- [ ] SharePoint uses `Sites.Selected` on the licensing site only.
- [ ] Every secret is a Railway variable; no secret is committed, and
      `.env` is git-ignored.
- [ ] The built frontend bundle contains no server secret
      (CI greps `frontend/dist`; repeat locally with
      `grep -rInE '(OPENAI_API_KEY|sk-[A-Za-z0-9_-]{16,}|GRAPH_CLIENT_SECRET)' frontend/dist`).
- [ ] No portal password or MFA code is stored anywhere
      (`docs/browser-session-security.md`).
- [ ] Restricted information remains masked in API responses and logs.
- [ ] Send approval is mandatory and self-approval is off.
- [ ] Final portal submission and signature remain human actions.
- [ ] Cross-entity document and information reuse remains blocked.
- [ ] `FORM_EXTERNAL_SUBMISSION_ENABLED` and
      `FORM_SIGNATURE_AUTOMATION_ENABLED` are `false`.

---

## 14. Known limitations

Honest gaps to keep in view; none of them blocks a controlled go-live, and each
has a documented workaround.

- **Test coverage is below the original gates, and both gates are now
  ratchets.** Every test passes (392 backend, 14 frontend), but measured
  coverage is 63.8% backend and ~14% frontend, against original gates of 85%
  and 45%. The shortfall is entirely Milestone 6 and 7 code, which shipped
  service logic ahead of service-level tests:

  | Module | Coverage |
  | --- | --- |
  | `app/workers/portal_jobs.py` | 0% |
  | `app/services/form_preparation_service.py` | 10.8% |
  | `app/services/submission_evidence_service.py` | 13.5% |
  | `app/services/portal_run_service.py` | 14.1% |
  | `app/services/document_packet_service.py` | 14.3% |
  | `app/services/portal_governance_service.py` | 16.0% |
  | `app/services/compliance_case_service.py` | 18.1% |
  | `app/services/information_registry_service.py` | 18.6% |

  Milestone 1–5 code remains well covered (133 files at 100%). The gates are
  set just below current level in `.github/workflows/ci.yml`, `Makefile`,
  `scripts/test.ps1`, and `frontend/vite.config.ts` so the pipeline is green
  and coverage cannot regress further. **Raise them as tests are added** —
  start with submission evidence and portal runs, the paths closest to a
  regulator filing. Until then, treat the portal and packet paths as
  verified by UAT and the pilot rather than by automated tests.
- **Backend image size.** The runtime image installs `requirements.lock.txt`,
  which includes the test and lint tools, in exchange for byte-identical
  dependency resolution between CI and deployment.
- **Frontend build-time configuration.** `VITE_*` values are baked into the
  bundle at build time; changing one requires a redeploy of the frontend
  service, not just a variable update.
- **Backup verification is manual.** Railway performs and reports backups; the
  restore test in section 9 is a periodic human procedure, not an automated
  check. Watch Railway's own backup notifications.
- **Alerts are pull-based.** `/api/v1/operations/status` reports the conditions
  worth acting on; there is no paging system. Pair it with Railway's
  deployment and crash notifications and a daily operator check during the
  pilot.
- **One general worker.** Queue families share a process. If one family becomes
  slow, split it into its own Railway service using the same image and a
  narrower `--queues` list.

## 15. Production checklist

- [ ] `backend`, `frontend`, `worker`, `scheduler`, and Postgres deployed
- [ ] `browser-worker` deployed only if portal assistance is approved
- [ ] staging and production fully separated
- [ ] all required variables set; `check_deployment` passes
- [ ] `alembic upgrade head` succeeded in the deployment log
- [ ] `/health/ready` returns 200; `/api/v1/operations/status` is clean
- [ ] scheduled backups enabled; one restore test completed and recorded
- [ ] master tracker imported and reconciled (`GO_LIVE_CHECKLIST.md`)
- [ ] UAT and pilot signed off
- [ ] rollback steps rehearsed and support contacts recorded

Related: [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) ·
[UAT checklist](docs/uat-checklist.md) ·
[pilot checklist](docs/pilot-checklist.md) ·
[staging acceptance](docs/milestone8-staging-acceptance.md) ·
[production data migration](docs/production-data-migration.md)

---

## 16. Deployment lessons from the first staging deploy

Recorded because each cost a failed deployment and none is obvious from the
documentation alone.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Health check fails; logs show `Invalid value for '--port': '$PORT'` | config commands run without a shell | wrap in `sh -c '…'` (also needed for `&&`) |
| `ModuleNotFoundError` for a package that exists locally | `railway up` honours `.gitignore`; an unanchored pattern such as `evidence/` also matches `app/evidence/` | anchor root-only ignores with a leading slash |
| `error parsing value for field "cors_origins"` | pydantic-settings JSON-decodes list fields before validators run | list settings are annotated `NoDecode` and accept `a,b` or `["a","b"]` |
| Build reported `SKIPPED` unexpectedly | Railway evaluates watch patterns from the repository root, including when a service root directory is set | use `/frontend/**` for the frontend service and repo-root paths for other services |
| A service builds the wrong Dockerfile | `railway up` uploads from the repo root regardless of the current directory | set `rootDirectory` and `railwayConfigFile` per service |
