# SharePoint operations runbook

Preflight:

```powershell
alembic upgrade head
python -m app.cli.sharepoint_diagnostics
python -m app.cli.sharepoint_bootstrap plan
python -m app.cli.sharepoint_bootstrap apply --confirm
python -m app.cli.sharepoint_bootstrap verify
python -m app.workers.runner --queues documents,sharepoint
```

Observe `/api/v1/integrations/sharepoint/status`, `/drives`, `/jobs`, and `/metrics`. Delta links and upload URLs are represented only by fingerprints or booleans.

For throttling, honor `Retry-After` and allow the bounded retry policy to run. For 403, stop retries and verify the selected-resource grant, expected app ID, site ID, and drive IDs. For 412, do not overwrite: reconcile the external edit and route it to review. For metadata-sync failure, retain the binary and retry only fields synchronization. For hash mismatch, revoke reuse and preserve both sides.

Recovery commands:

```powershell
python -m app.cli.reconcile_documents import-existing --drive-purpose MASTER_DOCUMENTS --dry-run
python -m app.cli.document_integrity verify --document-id <uuid>
```

Never paste tokens, delta links, preview URLs, or upload-session URLs into tickets. Never permanently delete a business document as incident remediation.

