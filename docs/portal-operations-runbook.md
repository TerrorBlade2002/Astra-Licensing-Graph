# Portal operations runbook

Run backend and classification worker separately, then the Vite portal:

```powershell
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
python -m app.workers.runner --queues classification
cd frontend; npm ci; npm run dev
```

Local development uses synthetic actor headers only under `APP_ENV=local|test`. Staging/production use Entra. Monitor `/health/ready`, `/metrics`, dashboard failures, expired claim leases, classification-run errors, outbox backlog, and correlation IDs. Never paste tokens or email bodies into tickets. Disable optional AI by setting `AI_CLASSIFICATION_ENABLED=false`; deterministic review remains available.

For a disputed decision, inspect classification versions, review revision/diffs, rule evidence, source email, task events, and audit records. Reclassify rather than editing an immutable machine version.
