# Document packet generation

Packet templates are versioned checklists scoped by jurisdiction, license type,
and case type. Matching checks document type, entity, jurisdiction, license
type, approval/reuse approval, lifecycle, current version, dates,
confidentiality, storage availability, and SHA-256 integrity.

Expired, superseded, quarantined, unapproved, wrong-entity, wrong-jurisdiction,
hash-invalid, or missing-source documents cannot enter a packet. Manual
selection is explicit and audited.

The manifest pins source document and version IDs, checksums, archive names,
included/omitted/missing items, case scope, creator, and timestamp. Its canonical
SHA-256 is stored with the packet. Approval freezes the snapshot; any later
document change requires a new packet version.

Manifest completion queues a durable packet job. That worker retrieves every
exact pinned SharePoint version, rechecks both catalogue and byte-level hashes,
creates a deterministic ZIP with the manifest and cover sheet, and stores it
behind a governed storage URI. Approval is blocked until that archive exists.
The controlled download endpoint verifies the stored archive hash and never
returns or logs a temporary Graph download or upload-session URL.

Approval only marks the packet ready for the next human-controlled operational
step. It does not transmit or submit it.
