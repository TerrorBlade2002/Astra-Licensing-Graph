# Reusable information registry

Definitions describe data type, validation, owner role, sensitivity, reuse
policy, freshness, and masked display behavior. Values are versioned and scoped
to legal entity plus optional jurisdiction, license, vendor, or case.

All values are envelope-encrypted with AES-256-GCM and record-bound associated
data. Fingerprints use keyed HMAC. Restricted plaintext is absent from list
responses, logs, metrics, telemetry, and AI prompts; explicit reveal requires
authority and creates an audit event.

Draft values cannot be reused. Approval requires an accountable owner and
supersedes the prior approved version in the same scope. Cross-entity reuse
requires a definition that permits it plus manager approval. Expired or stale
values cannot autofill; form preparation creates an information request instead.
Every use pins the value version, case/form/packet, actor, time, and purpose.
