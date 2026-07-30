# Portal operations runbook

Portal automation is disabled by default. Before enabling it, approve the portal review, activate a tested adapter version, authorize individual operators, configure an exact hostname allowlist, and retain all human-only settings as `true`.

Run the browser worker separately:

```powershell
docker compose up -d db
alembic upgrade head
uvicorn app.main:app
python -m app.workers.runner --queues portals
python -m app.workers.scheduling
```

Useful diagnostics:

```powershell
python -m app.cli.portal_diagnostics list
python -m app.cli.portal_diagnostics verify --portal-key <PORTAL_KEY>
python -m app.cli.portal_adapter_test --portal-key <PORTAL_KEY> --fixture <LOCAL_FIXTURE>
python -m app.cli.portal_run_reconcile --run-id <UUID>
python -m app.cli.submission_reconcile --run-id <UUID>
```

Monitor `/health/ready`, `/metrics`, failed portal jobs, `FAILED_REVIEW` runs, expired reviews and authorizations, session expiry, handoff age, adapter failures, upload failures, and ambiguous submission results. Metrics contain no portal account, license, confirmation, filename, or field-value labels.

On an unexpected page, changed terms, fee discrepancy, authorization failure, or adapter mismatch, keep the run stopped and open a review. On an ambiguous final action, reconcile; never start a second submission attempt.

To disable assistance, set both `PORTAL_AUTOMATION_ENABLED=false` and `BROWSER_AUTOMATION_ENABLED=false`, suspend affected portal reviews, and close active sessions. Temporary profiles are destroyed on closure. Never paste portal artifacts, cookies, credentials, codes, payment details, full HTML, or unrestricted screenshots into logs or tickets.
