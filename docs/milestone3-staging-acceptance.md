# Milestone 3 staging acceptance

Use synthetic documents only. Record correlation IDs and internal IDs; do not copy credentials or temporary URLs.

1. Permission boundary: diagnostics reads the selected site and configured libraries; an unrelated configured site is denied.
2. Bootstrap: review plan, apply with confirmation, verify drives/roots/columns/quarantine, and confirm no existing item was deleted.
3. Small upload: upload a synthetic PDF, compare size/hash, inspect columns/catalog/version, and download through the backend.
4. Resumable upload: use a synthetic file over the threshold, observe multiple ranges, inject one temporary failure, and verify resume/final hash.
5. Promotion: ingest a synthetic email PDF with Milestone 2, promote it, and verify original evidence, governed copy, and email/attachment links all remain.
6. Duplicate: promote identical content again; verify no second binary and a new source link.
7. Version: make an explicit new-version decision; verify version two current and version one auditable.
8. External rename/move: change a synthetic item, reconcile, and verify events and observed metadata.
9. External deletion: delete only the synthetic item, reconcile, and verify preserved database rows with `DELETED_EXTERNALLY` and revoked reuse.
10. Expiry: seed a near-expiry synthetic document, run lifecycle work, and verify alerts/state/reuse revocation.

Acceptance fails if any anonymous/organization sharing link is created, a live call occurs during automated tests, an email is sent or moved, or a binary/delta/upload/preview URL enters logs.

