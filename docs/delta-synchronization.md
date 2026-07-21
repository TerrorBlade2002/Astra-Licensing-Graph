# Delta synchronization

Implemented in [app/services/graph_sync.py](../app/services/graph_sync.py)
with the Graph calls in [app/graph/delta.py](../app/graph/delta.py).

## Per-folder checkpoints

`mailbox_sync_state` holds one row per (mailbox, folder):

- `delta_link` — the opaque checkpoint URL returned by Graph (never edited,
  never reconstructed, never exposed or fully logged),
- `last_delta_url_fingerprint` — SHA-256 of the link for diagnostics,
- `needs_rebaseline`, lease columns, last round statistics and errors.

## Initial baseline

When `delta_link` is NULL or `needs_rebaseline` is true:

```
GET /v1.0/users/{mailbox}/mailFolders/{folder-id}/messages/delta
    ?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,
             bodyPreview,hasAttachments,conversationId,internetMessageId,
             isRead,parentFolderId,lastModifiedDateTime
Prefer: odata.maxpagesize=50, IdType="ImmutableId"
```

Immutable IDs are requested everywhere (subscriptions, delta, message fetch)
so a folder move can never change the stored message identifier.

## Incremental rounds

The complete saved `delta_link` is called as-is — no added query parameters.
Before the call it must pass URL validation (HTTPS, configured Graph host,
v1.0 path, no credentials/fragments/ports).

## Pagination and the two links

Every page contributes `value[]` and then exactly one of:

- `@odata.nextLink` → validate, fetch the next page;
- `@odata.deltaLink` → the round is complete;
- neither → the response is invalid (non-retryable failure).

## Page-commit strategy

No database transaction stays open across an HTTP call:

```
loop:  call Graph (no tx) → open tx → upsert page + enqueue jobs → commit
after the final page only:  save new delta_link + stats, clear rebaseline
```

A crash or failure mid-round keeps the **previous** checkpoint; the round is
retried from it and replayed pages are harmless because every write is an
idempotent upsert keyed on `(mailbox_id, graph_message_id)` and ingestion
jobs coalesce per email. The checkpoint never advances after a partial
failure. A zero-change round is a success and still saves the newly returned
deltaLink.

## Non-removed entries

- New message → insert with `processing_state=DISCOVERED`,
  `synced_folder_membership=PRESENT`, plus processing event, audit event,
  outbox event, and one coalesced `INGEST_EMAIL` job.
- Existing message → refresh mutable Graph metadata (subject, read state,
  folder, etag, lastModified). The workflow state is **never** reset and no
  duplicate ingestion job is created while one is active.

## Removed entries

`@removed` may mean deletion *or* a move out of the synchronized folder; no
stronger claim is made than Graph's removal reason. The local email is
retained: membership becomes `REMOVED`, `removed_from_synced_folder_at` is
set, `current_graph_folder_id` is cleared only if it still pointed at the
synced folder, and a non-transition processing event is appended.

## Invalid delta state

On `syncStateNotFound` / `resyncRequired` / HTTP 410:

1. a fingerprint of the rejected link is preserved,
2. `needs_rebaseline=true`, `delta_link=NULL` in one controlled transaction,
3. an audit event records the rebaseline,
4. a fresh baseline `SYNC_FOLDER` job is enqueued,
5. no local email data is deleted — the baseline replays into upserts.

## Concurrency

A per-folder lease on `mailbox_sync_state` (`lease_owner`,
`lease_expires_at`) prevents concurrent rounds for the same folder; expired
leases are reclaimable so a crashed worker never blocks the folder forever.
