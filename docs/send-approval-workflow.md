# Send-approval workflow

Draft-content review and send approval are separate decisions. `Licensing.Reviewer` creates, edits, synchronizes, and submits a draft. `Licensing.Sender` approves the exact snapshot and queues send work. `Licensing.Admin` does not inherit Sender authority.

When separation of duties is enabled, neither the author nor the last editor can approve. Optional two-person mode records a first Sender approval and requires a different Sender before `APPROVED_TO_SEND`.

Approval binds subject, body hash, recipient hash, attachment hash, local revision, immutable Graph draft ID, Graph change key/eTag, response plan, and template version. Every mutation requires the caller's expected local revision and Graph change key/eTag. Any content, recipient, attachment, response-plan, Outlook, or AI revision invalidates approval.

The send page displays the mailbox, exact recipient count and external domains, subject, attachment count, approval timestamp, full body, document states, reviewer, and snapshot hash. A separate explicit checkbox is required before queueing. The send API requires that confirmation and an idempotency key, persists one durable job per approved snapshot, and returns Astra `202 SEND_QUEUED`; it does not call Graph.

A Sender can record `CHANGES_REQUESTED` or `REJECTED` as a send-approval decision. An approved or queued-but-unclaimed send can also be cancelled with a reason; cancellation locks the draft, cancels the pending durable job, and invalidates the approval. Once the worker holds the job, cancellation fails closed.
