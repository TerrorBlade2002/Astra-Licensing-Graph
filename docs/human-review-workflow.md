# Human review workflow

All initial classifications start `PENDING`. A claim changes the review to `IN_REVIEW` with a configurable lease. Mutations require `expected_revision`; stale writers receive 409 with the safe current revision.

- **Approve** accepts the machine proposal and permits task creation.
- **Correct** stores the reviewed overlay plus field-path machine/reviewed values and reasons.
- **Reject** requires a reason, creates no task, and leaves the email `CLASSIFIED`.
- **Request reclassification** requires a reason and queues a new immutable version.

Claims, decisions, diffs, actor, timestamps, and rationale are durable audit data. Auto-approval is disabled for initial rollout.
