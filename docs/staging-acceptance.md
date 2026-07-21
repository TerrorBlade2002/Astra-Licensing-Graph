# Manual staging acceptance runbook (Milestone 2)

This runbook requires a human operator with staging credentials. **No values
below are stored in source control.** Automated tests never perform these
steps — they run fully mocked.

## Operator prerequisites

Configure in the staging environment (e.g. environment variables or an
`.env` outside git):

| Setting | Value |
| --- | --- |
| `APP_ENV` | `staging` |
| `GRAPH_ENABLED` | `true` |
| `GRAPH_TENANT_ID` | *operator supplied* |
| `GRAPH_CLIENT_ID` | *operator supplied* |
| `GRAPH_CLIENT_SECRET` (or certificate settings) | *operator supplied, never committed* |
| `PUBLIC_BASE_URL` | public **HTTPS** URL reaching this deployment |
| `GRAPH_EXPECTED_TENANT_ID` | same tenant ID |

Seed the mailbox and Inbox folder (Graph folder ID from the prototype
inventory or Graph Explorer):

```powershell
alembic upgrade head
python -m app.cli.seed_dev             # or insert the real mailbox row
# Ensure a mailbox_folders row exists with display_name 'Inbox' and the real
# immutable Graph folder id for the licensing mailbox Inbox.
```

Live Graph subscription validation requires the webhook URLs to be publicly
reachable over HTTPS. For temporary development/staging exposure use an
approved HTTPS tunnel or reverse proxy of your organization's choosing — this
repository does not mandate or hard-code any third-party tunnel provider.

Start the components:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m app.workers.runner --queues subscriptions,sync,ingestion
python -m app.workers.scheduling
```

## Acceptance A — subscription

1. API + worker running; webhook URLs publicly reachable over HTTPS.
2. `python -m app.cli.graph_subscriptions ensure --mailbox astralicensing@astraglobal.com --folder Inbox`
3. Confirm Graph validated both webhook URLs (API logs show the
   validation-token requests; the ensure command returns without error).
4. `python -m app.cli.graph_subscriptions list` → row shows `ACTIVE`.
5. Confirm `expiration_at` is populated (~6 days by default).
6. Confirm the database stores only `client_state_hash` (64 hex chars):
   `SELECT client_state_hash FROM graph_subscriptions;` — no plaintext.

## Acceptance B — new message

1. Send a test email directly to the licensing shared mailbox.
2. `SELECT processing_status FROM graph_notification_receipts ORDER BY received_at DESC LIMIT 1;`
   → `ACCEPTED`.
3. `GET /api/v1/integrations/graph/jobs?job_type=SYNC_FOLDER` → job present.
4. After the worker runs: `graph_sync status ... ` shows a completed round.
5. `GET /api/v1/emails` → message appears; state history shows `DISCOVERED`.
6. Jobs listing shows the `INGEST_EMAIL` job (soon COMPLETED).
7. Email detail shows `full_message_json_*` and `raw_mime_*` populated;
   evidence files exist under `FILESYSTEM_EVIDENCE_ROOT`.
8. Attachment rows exist for any attachments.
9. Email `processing_state = ATTACHMENTS_SAVED`.
10. Confirm in Outlook that the message was **not** moved and nothing was
    sent from the mailbox (Sent Items unchanged).

## Acceptance C — incremental no-change

1. `python -m app.cli.graph_sync enqueue ... --reason MANUAL`; let the worker run.
2. Round completes with zero changes (`graph_sync status` →
   `last_change_count: 0`).
3. `last_completed_at` advanced and the delta fingerprint changed — a new
   checkpoint was saved.

## Acceptance D — update

1. Toggle the test message read/unread in Outlook.
2. Confirm a notification receipt arrives and the next sync round reports one
   updated change.
3. Confirm `emails.is_read` changed while `processing_state` remains
   `ATTACHMENTS_SAVED` (never reset).

## Acceptance E — removal

1. Manually move the test message from Inbox to another folder in Outlook.
2. Next Inbox delta round reports one removed entry.
3. The local email row still exists with its full history.
4. `synced_folder_membership = REMOVED`, `removed_from_synced_folder_at` set.

## Acceptance F — attachments

1. Send a dedicated test email containing one small PDF, one CSV, and one
   inline image.
2. After ingestion verify: three attachment rows, all `DOWNLOADED`,
   `sha256_checksum` populated, the inline image has `is_inline=true`,
   stored filenames are `<uuid>_<safe-name>` under the email's evidence
   directory (no traversal possible), and the email reaches
   `ATTACHMENTS_SAVED`.

## Acceptance G — subscription renewal

1. Set a short staging window, e.g.
   `GRAPH_SUBSCRIPTION_RENEWAL_WINDOW_MINUTES=14400` (10 days) so the current
   subscription is inside the window.
2. Run `python -m app.workers.scheduling --once` and the worker.
3. Confirm `expiration_at` extended and `last_renewed_at` set.
4. Confirm exactly one active subscription row exists for the folder
   (the partial unique index makes duplicates impossible).

## Acceptance H — lifecycle simulation

Do **not** disrupt the live Astra subscription to fabricate events. Instead
post mocked lifecycle payloads at the staging endpoint using the real
subscription ID and a deliberately *wrong* clientState first (expect an
`INVALID_CLIENT_STATE` receipt and no action), then verify handling logic in
the mocked test suite (`tests/api/webhooks/test_lifecycle_api.py`) which
covers `reauthorizationRequired`, `subscriptionRemoved`, and `missed`
end-to-end against synthetic subscriptions.

A real reauthorization/removal event arriving naturally during staging will
be handled automatically; verify through
`GET /api/v1/integrations/graph/subscriptions` and the jobs listing.
