# Document lifecycle, approval, and reuse

Storage status (`UPLOADING`, `AVAILABLE`, `FAILED`, `QUARANTINED`, `MISSING`, `DELETED_EXTERNALLY`) is separate from lifecycle (`ACTIVE`, `EXPIRED`, `SUPERSEDED`, `ARCHIVED`, `QUARANTINED`, `MISSING`, `DELETED_EXTERNALLY`) and approval (`UNREVIEWED`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`).

Existence in SharePoint never implies approval. Reuse approval additionally requires an active approved document, available latest version, verified hash, complete metadata, non-expired dates, and an allowed confidentiality policy. Expiry and supersession revoke reuse approval without deleting or moving the file.

Every material mutation appends a `document_metadata_events` row. SharePoint rename/move updates observed filename/parent metadata but does not silently change business category. External deletion preserves the database catalog, marks document/version `DELETED_EXTERNALLY`, revokes reuse, and emits an event.

Development-header actors are rejected in production. The authorization policy boundary must be replaced by Entra role/claim checks before the final portal is exposed.

