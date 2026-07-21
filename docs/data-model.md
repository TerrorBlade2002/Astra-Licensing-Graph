# Data model

All tables use UUID primary keys, TIMESTAMPTZ timestamps, snake_case names,
and explicitly named constraints (see `app/db/naming.py`). Domain
enumerations are TEXT columns guarded by named CHECK constraints — native
PostgreSQL ENUM types are deliberately avoided in this milestone because they
make early-stage value changes expensive to migrate.

## Tables

| Table | Purpose |
| --- | --- |
| `mailboxes` | Monitored shared mailboxes (currently one: the licensing mailbox). |
| `mailbox_folders` | Graph folder inventory per mailbox (workflow destinations). |
| `mailbox_sync_state` | Per-folder delta link + lease bookkeeping for future sync workers. |
| `emails` | One row per discovered Graph message; carries the processing state machine. |
| `email_recipients` | TO/CC/BCC/REPLY_TO rows per email, ordinal-ordered. |
| `email_attachments` | Attachment metadata, SHA-256, storage URI, download status. |
| `classifications` | Versioned classification results; exactly one `is_current` per email. |
| `classification_reviews` | Human decisions (APPROVED/CORRECTED/REJECTED) on classifications. |
| `licensing_tasks` | Durable work items derived from approved classifications. |
| `task_requested_items` | Checklist of requested information items per task. |
| `outbound_drafts` | Reply drafts (Graph draft IDs, statuses); nothing is sent in M1. |
| `email_processing_events` | Append-only state-transition history per email. |
| `audit_events` | Append-only audit trail (actor, action, before/after). |
| `outbox_events` | Transactional outbox for future Service Bus publication. |

## Relationships

```
mailboxes 1─* mailbox_folders 1─* mailbox_sync_state
mailboxes 1─* emails 1─* email_recipients
                     1─* email_attachments
                     1─* classifications 1─* classification_reviews
                     1─* email_processing_events
                     1─* licensing_tasks 1─* task_requested_items
                                         1─* outbound_drafts
```

Task foreign keys to email/classification/review use `ON DELETE SET NULL`:
a task must survive even if its source rows are pruned. Child rows of an
email (recipients, attachments, events, classifications) cascade with it.
Emails cannot cascade away with a mailbox (`RESTRICT`).

## Important indexes

- `uq_mailboxes_address_lower` — case-insensitive unique mailbox address
  (functional index on `lower(address)`; addresses are also normalized to
  lowercase at every application boundary).
- `uq_emails_graph_message` — `(mailbox_id, graph_message_id)` dedupe on the
  Graph identifier.
- `uq_emails_internet_message_id` — partial unique `(mailbox_id,
  internet_message_id) WHERE internet_message_id IS NOT NULL`; RFC message
  IDs dedupe cross-folder copies but may legitimately be absent.
- `ix_emails_state_received` — the worklist query (`mailbox`, `state`,
  `received_at`).
- `ix_emails_next_retry_at` — partial index for the retry scheduler.
- `uq_classifications_current` — partial unique on `email_id WHERE
  is_current`; enforces exactly one live classification per email while
  keeping full version history.
- `uq_email_attachments_dedupe` — partial unique `(email_id, sha256_checksum,
  original_filename) WHERE sha256_checksum IS NOT NULL`; a re-download of the
  same content cannot create a duplicate row.
- `uq_outbox_events_idempotency_key` — exactly-once handoff to the future
  queue publisher.

## Deduplication strategy

1. Primary identity: `(mailbox_id, graph_message_id)` — what Graph gives us.
2. Secondary identity: `(mailbox_id, internet_message_id)` partial unique —
   catches the same logical message re-appearing under a different Graph ID
   (e.g. after a move in some scenarios).
3. Attachments: content hash + filename per email.
4. Prototype import: records whose Graph message ID already exists are
   skipped entirely, never merged.

## Why Graph IDs are TEXT

Microsoft Graph message/folder/attachment IDs are opaque, variable-length,
base64-ish strings with no documented maximum and no stable structure. They
are stored as TEXT, never parsed, never assumed unique across mailboxes, and
compared only byte-for-byte.

## Why delta links are opaque

`mailbox_sync_state.delta_link` is a full Graph URL that embeds a server-side
sync token (and can embed tenant-identifying material). It is:

- treated as an opaque blob (TEXT),
- never exposed through any API response,
- never logged beyond a 32-character prefix (`redact_delta_link`),
- replaced wholesale on every sync round, never edited.
