# Communications operations runbook

- Permission boundary: run `python -m app.cli.communication_diagnostics permissions --mailbox astralicensing@astraglobal.com`, then `python -m app.cli.communication_diagnostics scope-denial --mailbox <unrelated-synthetic-mailbox>`. The first is read-only and never sends; the second must report `DENIED`.
- Missing Graph draft: set failed review, inspect immutable IDs, and recreate only through an authorized new revision. For ambiguous `createReply`, use draft reconciliation; it accepts only one candidate from the source conversation and never repeats creation automatically.
- Stale approval or Outlook edit: synchronize, preserve the observed revision, invalidate approval, and repeat content review.
- Graph 401: the send client refreshes once. A second 401 goes to review.
- Graph 403: verify application permissions and mailbox-scoped Exchange RBAC; do not retry blindly.
- Graph 429: use bounded durable backoff. HTTP 408/5xx from the non-idempotent send or move is ambiguous and must reconcile before any new action. Never replay an accepted or ambiguous send.
- Missing Sent Items copy: run bounded reconciliation; retain `DELIVERY_UNKNOWN` and alert after the observation window.
- Reconciliation window: the first check is delayed by `COMMUNICATION_SEND_RECONCILIATION_INITIAL_DELAY_SECONDS`; the durable retry budget and `COMMUNICATION_SEND_RECONCILIATION_MAX_SECONDS` bound observation. Exhaustion becomes explicit review, never resend.
- Shared-mailbox safeguard: retain and periodically verify Exchange `MessageCopyForSentAsEnabled` and `MessageCopyForSendOnBehalfEnabled` so the shared mailbox keeps its Sent Items copies.
- NDR: record `NDR_RECEIVED`; Sent Items presence alone was never delivery confirmation.
- Move ambiguity: run `python -m app.cli.move_reconcile --email-id <uuid>`; it only inspects state and never repeats the move.
- Invalid destination: correct the task/folder configuration with Manager authorization before queuing a new move.
- Stuck job or stale lease: inspect safe IDs, release the expired lease, and retain the original idempotency key.
- Large attachment: keep disabled unless the shared-mailbox staging test passed. Upload URLs are opaque, memory-only, and must never appear in logs.
- Optional AI wording: keep `RESPONSE_AI_DRAFTING_ENABLED=false` unless provider approval, data-policy acknowledgement, model/key configuration, `store=false`, and review procedures are all in place. AI output is always a new review-stage revision.
