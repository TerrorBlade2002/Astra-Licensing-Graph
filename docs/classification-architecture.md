# Classification architecture

`CLASSIFY_EMAIL` is eligible only at `ATTACHMENTS_SAVED`. The worker loads normalized evidence, ends its read transaction, runs deterministic rules, optionally calls an approved model provider, then opens a short transaction. Verified deterministic identity and evidence win during merge. Strict schema/evidence validation precedes an immutable classification version, run record, pending review, audit/outbox records, and `ATTACHMENTS_SAVED -> CLASSIFIED`.

The input fingerprint covers subject/body, attachment metadata, schema, and rule-set identity. Versions retain parents; only one classification per email is current. A model outage never erases sufficient deterministic results and always adds a review reason.

The shared contract is `ClassificationOutputV1` in `app/classification/schema.py`; unknown properties are rejected. Evidence quotes must occur in the normalized current message, filenames must be present in attachment metadata, and destinations must be configured.
