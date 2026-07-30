# Production data migration

How the approved source files become the system of record. It reuses the
Milestone 6 importers; nothing new is built for migration.

Mechanics of the importer itself are in
[master-tracker-migration.md](master-tracker-migration.md). The signed
step-by-step record lives in [GO_LIVE_CHECKLIST.md](../GO_LIVE_CHECKLIST.md).

## What is migrated

| Data | Route |
| --- | --- |
| Legal entities, jurisdictions, licence types | created first in the registry; the importer resolves names against them and never invents one |
| Current licence tracker | `python -m app.cli.import_master_tracker` |
| Bonds | tracker columns `BOND_*` |
| Annual reports | tracker column `ANNUAL_REPORT_DATE` → annual-report obligations |
| Current renewal dates | tracker columns `EXPIRATION_DATE`, `RENEWAL_DUE_DATE` |
| Current open licensing cases | opened from obligations after import, or entered by the process owner |
| Approved reusable information | information registry, each value approved by its owner |
| Approved documents | document repository (`python -m app.cli.migrate_evidence`, or promotion from email) |
| Current responsible owners | tracker column `RESPONSIBLE_OWNER` |

## Process

1. **Obtain** the current approved source files from the process owner. Only
   files they confirm as authoritative.
2. **Preserve** an untouched copy: record the SHA-256 and store the original in
   the governed document repository. Production configuration refuses a
   filesystem-only copy for tracker evidence.
3. **Dry run** — `import_master_tracker plan`. Nothing is written to the
   inventory.
4. **Read the counts** — inserted, updated, skipped, conflict, error.
5. **Review conflicts manually.** A conflict means the system holds better
   evidence than the spreadsheet, or two records match one row. Neither is
   resolved automatically.
6. **Correct the source data or the mapping**, never the decision logic. Re-run
   the dry run until only expected actions remain.
7. **Apply** — `import_master_tracker run --confirm`. Each row commits in its
   own savepoint, so one bad row cannot roll back the run.
8. **Prove idempotency** — re-run the identical import; every row should be
   `skip`.
9. **Reconcile** — `python -m app.cli.migration_reconcile check --expected
   expected-counts.json` (exits non-zero on mismatch), then
   `python -m app.cli.licensing_data_quality run`.
10. **Obtain process-owner approval** in writing before the data is used for
    real filings.

## Expected-counts file

Counts taken from the source files, before import:

```json
{
  "legal_entities": 0,
  "licenses_active": 0,
  "licenses_expiring_120_days": 0,
  "bonds_total": 0,
  "annual_report_obligations": 0,
  "cases_open": 0,
  "obligations_overdue": 0,
  "licenses_missing_renewal_date": 0
}
```

Available keys are those returned by `migration_reconcile totals`; an unknown
key is rejected rather than ignored.

## Rollback

A migration is undone by restoring the database backup taken immediately
before the apply step (DEPLOYMENT.md section 9), or by a reviewed compensating
change. Import history is evidence and is never deleted.

## What is deliberately not built

No generalized migration platform, no transformation engine, no reconciliation
database tables. The importers, one reconciliation command, and a signed
checklist are enough for a one-time cutover.
