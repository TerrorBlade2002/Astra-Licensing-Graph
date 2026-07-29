# Controlled response drafting

Milestone 5 starts only after a reviewed classification has produced a licensing task. A response plan records whether a response is required, the response type, recipient mode, template version, signature, readiness result, and routing destination. Classification approval is never send approval.

Active templates render inside a Jinja sandbox with strict undefined values and an explicit variable allowlist. Template values come from reviewed application records; portal input cannot override an authoritative vendor, jurisdiction, license identifier, due date, requested item, mailbox, or response reference.

Optional AI output is wording-only and fail-closed. It requires the response-specific feature flag, provider/data-policy approval, and the explicit `licensing_response_sanitized` allowed data class. It uses strict structured output with no tools/files/storage, verifies declared claims against verified requested items or approved selected-document metadata, and creates a normal `REVIEW_IN_PROGRESS` revision. It cannot select recipients, BCC, documents, approvals, Graph operations, filing submission, send, move, or completion.

Each local edit creates an immutable `outbound_draft_versions` row. Body, recipient, attachment, and aggregate snapshot hashes make revisions comparable. Graph draft creation uses `createReply` by default, imports the recipients Graph actually generated, applies reviewed content, retrieves the draft again, and retains the immutable message ID, change key, and eTag. A portal edit is pushed to that same draft with optimistic concurrency. Outlook-side changes become a new observed revision and invalidate approval.

Draft and template validation rejects unresolved placeholders, unsafe HTML, false attachment references, and oversized bodies. Attachment selection and upload produce reviewable revisions. Removing an uploaded attachment deletes the exact Graph attachment ID, reconciles the draft metadata, and invalidates approval before the external mutation can race a queued send.

An ambiguous `createReply` is never repeated. A durable reconciliation queries the shared Drafts folder by the source conversation and accepts only one unambiguous draft candidate. Missing or multiple candidates remain review work.
