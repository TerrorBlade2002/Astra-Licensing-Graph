# Task workflow

Only `APPROVED` or `CORRECTED` reviews create tasks. The transaction locks review/classification/email, checks `CLASSIFIED`, reuses `review:{id}:primary` idempotently, creates task/requested items/events/audit/outbox, and moves the email to `TASK_CREATED` atomically.

Routing is deterministic: information required, bonds, NMLS, regulators, invoices, proof, RASI renewals, or internal follow-up. Overrides require a reason. States are `OPEN`, `IN_REVIEW`, `WAITING_FOR_INFO`, `READY_TO_SEND`, `COMPLETED`, `CANCELLED`, plus controlled `BLOCKED`/`OVERDUE` transitions.

`READY_TO_SEND` is a work posture only. Milestone 4 has no draft, send, mailbox move, or regulator-submission trigger.
