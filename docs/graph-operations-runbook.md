# Graph operations runbook

All commands run from the repo root with the venv active and `DATABASE_URL`
exported. No command prints tokens, secrets, clientState, or full delta links.

## Inspecting subscriptions

```powershell
python -m app.cli.graph_subscriptions list
# API equivalents:
# GET /api/v1/integrations/graph/status
# GET /api/v1/integrations/graph/subscriptions
```

Healthy: one row per watched folder with `status=ACTIVE` and `expiration_at`
comfortably in the future.

## Renewal and recreation

```powershell
# Idempotent — creates, renews, or no-ops as needed:
python -m app.cli.graph_subscriptions ensure --mailbox astralicensing@astraglobal.com --folder Inbox
python -m app.cli.graph_subscriptions renew --subscription-id <internal-uuid>
```

The scheduler (`python -m app.workers.scheduling`) renews automatically inside
`GRAPH_SUBSCRIPTION_RENEWAL_WINDOW_MINUTES`. If `graph_subscription_renewal_failures_total`
grows, run `ensure` manually and check `last_error_code` on the row.

Remote/local drift:

```powershell
python -m app.cli.graph_subscriptions reconcile --mailbox astralicensing@astraglobal.com --dry-run
# Only after human review of the dry-run output:
python -m app.cli.graph_subscriptions reconcile --mailbox ... --delete-unknown-remote
```

An unknown remote subscription is never deleted without the explicit flag.

## Manual sync

```powershell
python -m app.cli.graph_sync enqueue --mailbox astralicensing@astraglobal.com --folder Inbox --reason MANUAL
python -m app.cli.graph_sync status  --mailbox astralicensing@astraglobal.com --folder Inbox
```

Enqueue coalesces onto any active sync job for the folder.

## Stuck jobs

- `GET /api/v1/integrations/graph/jobs?status=FAILED_REVIEW` lists jobs that
  exhausted retries or hit non-retryable failures; each carries a sanitized
  `last_error_code`.
- Expired leases (crashed workers) are recovered automatically by the
  scheduler; a stuck `RUNNING` job with a past `lease_expires_at` simply
  becomes claimable again.
- A folder whose sync lease is wedged: check `graph_sync status` for
  `lease_owner`; leases expire after `GRAPH_JOB_LEASE_SECONDS` and recover on
  the next attempt.

## Invalid delta state

Symptoms: `last_error_code=delta_state_invalid`, `needs_rebaseline=true`,
`graph_delta_rebaseline_total` incremented. This is self-healing: a baseline
job is enqueued automatically and local data is preserved. Investigate only
if rebaselines repeat — that usually means the folder ID changed or the
mailbox was migrated.

## Graph auth and throttling

- **401 once** — normal; the client force-refreshes the token and retries.
- **Repeated 401 (`persistent_401`)** — the credential is invalid/expired.
  Verify with `python -m app.cli.graph_diagnostics token --no-print-token`
  and rotate the client secret in the deployment environment (never in git).
- **403** — non-retryable. Almost always an Exchange RBAC scope problem or a
  resource outside the app's mailbox grant. Jobs go to FAILED_REVIEW.
- **429** — expected under load; the client honours `Retry-After`
  (`graph_429_total` tracks volume). Sustained 429 → lower worker concurrency
  or raise `GRAPH_WORKER_POLL_INTERVAL_SECONDS`.
- **5xx** — retried with bounded jittered backoff; persistent 5xx exhausts
  attempts into FAILED_REVIEW.

## Worker heartbeat failure

`graph_worker_heartbeat_age_seconds` grows or
`GET /api/v1/integrations/graph/status` shows a stale
`worker_heartbeat_age_seconds`: the worker process died. Restart
`python -m app.workers.runner --queues subscriptions,sync,ingestion`; leases
recover automatically and pending jobs resume.

## Evidence-store failure

Filesystem errors (disk full, permissions) surface as
`storage_or_network_error` retryable job failures. Writes are atomic
(temp-file + rename), so partial artifacts are never referenced; fix the
underlying disk issue and let retries drain. `MAX_RAW_MIME_BYTES` /
`MAX_ATTACHMENT_BYTES` violations are policy outcomes, not storage failures:
oversized attachments are quarantined and MIME-limit hits go to review.
