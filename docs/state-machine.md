# Email processing state machine

Implemented in `app/domain/transitions.py` (pure rules) and
`app/services/email_state.py` (atomic execution).

## Diagram

```
DISCOVERED ─▶ FETCHED ─▶ ATTACHMENTS_SAVED ─▶ CLASSIFIED ─▶ TASK_CREATED ─▶ MOVED ─▶ COMPLETED
     │            │               │            │  ▲   │           │            │
     │            │               │            └──┘   │           │            │      (CLASSIFIED ▶ CLASSIFIED
     ▼            ▼               ▼                   ▼           ▼            ▼       = explicit reclassify)
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │ FAILED_RETRYABLE ──▶ (recorded resume_state)      FAILED_RETRYABLE ─▶ FAILED_REVIEW │
   │ FAILED_REVIEW ─────▶ manual reset only (explicit target, manual_reset=True)         │
   └─────────────────────────────────────────────────────────────────────────────┘
```

## Transition table

| From | Allowed targets |
| --- | --- |
| DISCOVERED | FETCHED, FAILED_RETRYABLE, FAILED_REVIEW |
| FETCHED | ATTACHMENTS_SAVED, FAILED_RETRYABLE, FAILED_REVIEW |
| ATTACHMENTS_SAVED | CLASSIFIED, FAILED_RETRYABLE, FAILED_REVIEW |
| CLASSIFIED | CLASSIFIED (reclassify), TASK_CREATED, FAILED_RETRYABLE, FAILED_REVIEW |
| TASK_CREATED | MOVED, FAILED_RETRYABLE, FAILED_REVIEW |
| MOVED | COMPLETED, FAILED_RETRYABLE, FAILED_REVIEW |
| FAILED_RETRYABLE | the recorded `resume_state`, FAILED_REVIEW |
| FAILED_REVIEW | any pipeline state, only with `manual_reset=True` |
| COMPLETED | — (terminal) |

## Retry behaviour

Entering `FAILED_RETRYABLE`:

- `resume_state` is set to the state the email held when the failure occurred
  (unless it was already a failure state),
- `retry_count` is incremented,
- `last_error_code` / `last_error_message` are recorded,
- `next_retry_at` may be scheduled by the caller.

A retry transitions back to exactly `resume_state`; any other pipeline target
is rejected. Successfully leaving a failure state clears `resume_state` and
the error fields.

## Terminal-state rules

`COMPLETED` accepts no further transitions of any kind. `FAILED_REVIEW` is
sticky: only an explicit manual reset (a human action carried as
`manual_reset=True`, audited as such) can move it back into the pipeline, and
never directly to `COMPLETED`.

## Transaction behaviour

`transition_email_state` performs, in **one** database transaction:

1. `SELECT ... FOR UPDATE` on the email row (serializes concurrent workers).
2. Optional `expected_current_state` check → `StateConflictError` (409).
3. Matrix validation → `InvalidStateTransitionError` (409). Invalid
   transitions are always raised, never silently skipped.
4. Email row update (state, resume/error/retry bookkeeping, timestamps).
5. `email_processing_events` insert.
6. `audit_events` insert (actor is mandatory).
7. `outbox_events` insert when the target state is significant
   (CLASSIFIED, TASK_CREATED, COMPLETED, FAILED_REVIEW). The outbox
   idempotency key is derived from the processing-event UUID created in the
   same transaction, so event and outbox row commit or roll back together.

Any failure rolls back the entire set — the integration tests assert that a
forced failure leaves zero partial rows.
