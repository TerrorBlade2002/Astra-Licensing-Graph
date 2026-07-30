# Master tracker migration

The importer accepts CSV and XLSX within configured size/row limits. It rejects
macro-enabled extensions, never executes macros, and loads XLSX with formula
evaluation disabled. Formula cells are reported and treated as literal source
data.

The first pass discovers sheets, headers, samples, and formula counts. An admin
maps source columns. The dry run normalizes dates/statuses/channels, resolves
registered scope, fingerprints rows, and classifies insert, update, unchanged,
conflict, or error.

Applying requires `confirm=true`. Each row uses a savepoint so one failure does
not corrupt the whole run. Original source data, normalized data, fingerprint,
decision, target, and errors are retained. Verified newer records are never
silently overwritten.

The API first preserves the original workbook in the governed document
repository and links that document to the import run. Production configuration
rejects filesystem-only tracker evidence. Worker payloads carry only governed
document IDs, mappings, and sheet names—never workbook bytes.

Reconciliation uses the import report and data-quality command. Rollback is a
reviewed database restoration or compensating inventory change; import history
itself remains evidence.
