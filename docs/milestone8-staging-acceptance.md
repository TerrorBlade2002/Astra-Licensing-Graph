# Milestone 8 staging acceptance

Deployment, integration, and end-to-end verification in the Railway **staging**
environment. Use approved internal recipients and the synthetic or approved
test portal only. Record a result only for a step that was actually executed.

## A. Deployment

1. `backend`, `frontend`, `worker`, `scheduler`, and Postgres deploy from the
   repository; `browser-worker` deploys only when portal assistance is enabled.
2. The backend pre-deploy runs `python -m app.cli.check_deployment --compact`
   and `alembic upgrade head`; both succeed and appear in the deployment log.
3. Remove a required variable and confirm the deployment fails at pre-deploy;
   restore it.
4. `/health/live` and `/health/ready` return 200; Railway routes traffic only
   after readiness passes.
5. `GET /api/v1/system/version` reports the expected migration revision.
6. `GET /api/v1/operations/status` shows a fresh worker heartbeat, a scheduler
   run within the last ten minutes, and no unexpected alert.
7. The frontend serves the production build, deep links resolve through the SPA
   fallback, and no dev server is running.
8. `grep -rInE '(OPENAI_API_KEY|sk-[A-Za-z0-9_-]{16,}|GRAPH_CLIENT_SECRET|postgresql://)' frontend/dist`
   returns nothing.
9. Scheduled backups are enabled; one restore test is completed per
   DEPLOYMENT.md section 9.

## B. Migration and reconciliation

10. Dry-run the approved tracker copy; record insert / update / skip /
    conflict / error counts.
11. Resolve conflicts, apply, then re-run the identical import and confirm only
    `skip` rows result.
12. `python -m app.cli.migration_reconcile check --expected expected-counts.json`
    exits zero.
13. `python -m app.cli.licensing_data_quality run` shows no unresolved ERROR
    finding.

## C. Integration flows

**Flow A — email ingestion.** A test email reaches the shared mailbox; the
webhook or scheduled delta sync detects it; the message and attachments are
stored; the email reaches `ATTACHMENTS_SAVED`.

**Flow B — classification and task.** The email is classified, a reviewer
checks the result, a task is created, and the email reaches `TASK_CREATED`.

**Flow C — document and packet.** An attachment is promoted (or a document
selected), stored approved in SharePoint, and a packet is generated containing
the correct entity and current document versions.

**Flow D — controlled response.** A draft is generated and edited by a
reviewer; a *different* authorized sender approves; the test email is sent to
an approved internal recipient; the sent copy is reconciled; the original
message is moved.

**Flow E — renewal case.** A licence due date creates an obligation; a renewal
case opens; vendor questions are tracked; internal answers are collected; a
packet is built; a form is prepared; signed evidence is recorded; the renewed
licence updates the inventory.

**Flow F — portal assistance** (only when enabled). An approved portal run is
created; a human logs in; approved fields and documents are entered; the system
stops for MFA, CAPTCHA, attestation, payment, and Submit; the human performs
the final action; confirmation evidence is recorded.

## D. One end-to-end staging test

14. A single scenario passes through: email → classification → review → task →
    document → response → case → form → portal handoff → submission evidence.
    Record the case key and the audit-event IDs at each step.

## E. Boundaries

15. Production configuration refuses development authentication, wildcard CORS,
    filesystem evidence, disabled send approval, disabled human review,
    disabled human-only portal controls, and external form submission.
16. No secret, token, delta link, portal password, MFA code, browser cookie, or
    payment credential appears in logs, the status endpoint, the database, or
    deployment output.
17. Staging services connect only to staging resources; no staging worker can
    reach the production database, mailbox, SharePoint site, or portal account.

## Results

Record migration output, reconciliation totals, backend test results, frontend
typecheck/lint/test/build results, the deployment log excerpt, and the
end-to-end evidence — for the steps that were actually run, and no others.

### Executed on 2026-07-30

Railway project `astra-licensing`, environment `staging`
(project `c2858170-82ee-4b51-a255-3729e1c3b724`).

| Check | Result |
| --- | --- |
| Backend suite | 392 passed, 0 failed (`tests/unit`, `tests/api`, `tests/integration`) |
| Backend coverage | 63.8% — see DEPLOYMENT.md known limitations |
| Ruff format / lint / mypy | clean |
| Frontend typecheck / lint / tests / build | clean; 14 tests passed |
| Local images | backend and frontend build; run as non-root; health endpoints 200 |
| `check_deployment` | passes; exits non-zero on an incomplete configuration |

Deployed services (section A):

| Service | State | Evidence |
| --- | --- | --- |
| Postgres | online, private network only | internal hostname does not resolve publicly |
| backend | online, `https://backend-staging-2030.up.railway.app` | `/health/live` and `/health/ready` 200 |
| frontend | online, `https://frontend-staging-7f87.up.railway.app` | `/healthz` 200, SPA deep links 200 |
| worker | online | log: `Worker starting families=["communications","documents","graph","licensing"]` |
| scheduler | cron `*/5 * * * *`, exits after each pass | log: `Scheduler cycle completed licensing_jobs=4` |
| browser-worker | not deployed | portal assistance not approved |

| Verification | Result |
| --- | --- |
| Pre-deploy migration | all 7 revisions applied; `/api/v1/system/version` reports `0007_portal_assistance` |
| Health check gating | Railway routes traffic only after `/health/ready` passes |
| Operations status | `api_status` and `database_status` OK, no alerts, worker heartbeat fresh |
| Scheduler → worker loop | cron enqueued 4 licensing jobs; worker completed them (0 pending, 0 failed-review) |
| Read endpoints | dashboards, integrations, emails, tasks, documents, audit events all 200 |
| CORS | portal origin allowed; unknown origin receives no allow-origin header |
| Frontend bundle | targets the backend domain; contains no server secret |
| Database backups | **not enabled** — `volumeInstanceBackupScheduleUpdate` returns *Not Authorized* on this Railway plan |

Not executed: production environment, restore test, production data migration,
UAT, and pilot. Those sections remain unchecked above.
