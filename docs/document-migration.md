# Filesystem-to-SharePoint migration

Only governed database records are eligible; the tool never crawls arbitrary disk directories.

```powershell
python -m app.cli.migrate_evidence plan --source filesystem --target sharepoint
python -m app.cli.migrate_evidence run --source filesystem --target sharepoint --confirm
python -m app.cli.migrate_evidence verify --source filesystem --target sharepoint
```

Plan reports eligibility, already-migrated rows, missing sources, hash mismatches, unknown routes, and estimated bytes. Run recomputes SHA-256, uploads using the configured route, verifies size/hash, then changes durable SharePoint identifiers and appends a migration event. Repetition skips finalized records.

Local sources remain untouched for the operator-defined rollback window. Rollback restores catalog pointers from the recorded source URI and events after review; it never deletes SharePoint files automatically. Partial failures retain the prior source and retryable catalog state.

