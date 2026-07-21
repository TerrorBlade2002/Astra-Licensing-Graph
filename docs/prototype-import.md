# Prototype import

`python -m app.cli.import_prototype` migrates the PowerShell proof-of-concept
JSON files into PostgreSQL. The prototype tree now lives in
`prototype-data/` (moved out of the repository root; the directory is
gitignored because it contains real Graph identifiers).

## Usage

```powershell
# Validate only — no rows are written
python -m app.cli.import_prototype `
  --root "C:\Users\<user>\Desktop\Astra-Licensing-Graph\prototype-data" `
  --mailbox "astralicensing@astraglobal.com" `
  --dry-run

# Real import
python -m app.cli.import_prototype --root ".\prototype-data" --mailbox "astralicensing@astraglobal.com"
```

`--root` defaults to `PROTOTYPE_IMPORT_ROOT` (`./prototype-data`). The JSON
report is printed to stdout; logs go to stderr, so stdout stays parseable.
Email bodies never appear in console output.

## Supported source files

| File | Content |
| --- | --- |
| `processing/state/email_processing_state.json` | Master record list incl. history |
| `processing/raw-emails/<key>/message.json` | Structured Graph message |
| `processing/raw-emails/<key>/message.eml` | Raw MIME (referenced as `file://` URI) |
| `processing/attachments/<key>/attachment_manifest.json` | Attachment metadata + SHA-256 |
| `processing/classifications/<key>/classification.json` | Classification result |
| `processing/reviews/<key>/review.json` | Human review decision |
| `processing/tasks/LIC-<key>.json` | Durable task |
| `processing/tasks/tasks_index.json` | (read implicitly through task files) |
| `mailbox_folders.json` (root) | Folder inventory |

## Wrapper-shape tolerance

PowerShell's `ConvertTo-Json` produced several shapes for "a list of
records". `flatten_records` normalizes all of them:

- single object `{...}`
- array `[{...}]`
- nested arrays `[[{...}]]` (any depth)
- wrapper objects `{"records": [...]}`, `{"value": [...]}`, `{"items": [...]}`

Files are read as `utf-8-sig` (PowerShell writes a BOM), and 7-digit
fractional-second timestamps are parsed correctly.

## Mapping rules

- State record → `emails` (processing state, retry/error fields, timestamps);
  `source_payload` records the prototype `record_key`.
- `message.json` → subject/sender/body/recipients (addresses lowercased).
- Manifest entries → `email_attachments`; local Windows paths become
  `file://` URIs; SHA-256 values preserved.
- `history[]` → `email_processing_events` with `event_type =
  "prototype_history"` and the **original** timestamps, so a COMPLETED
  record keeps its true historical progression.
- `classification.json` → `classifications` version 1, `is_current = true`;
  the `llm` block maps to `model_name` / `model_output`; evidence paths are
  converted to `file://` URIs.
- `review.json` → `classification_reviews`; `reviewed_classification` is
  stored as `corrected_classification` only for CORRECTED decisions.
- Task file → `licensing_tasks` (task_key = prototype task_id) plus
  `task_requested_items` from `requested_information`.
- Draft fields on the state record → one `outbound_drafts` row (status SENT
  in the completed example).
- Graph IDs are preserved verbatim as TEXT.

## Idempotency

An email whose `(mailbox, graph_message_id)` already exists is **skipped**
wholesale (never merged or updated), so repeated imports cannot duplicate or
clobber history. Folders and the mailbox row are create-if-missing.

## Transactions and error isolation

Each prototype record imports inside its own SAVEPOINT; a malformed record
rolls back alone, is reported with a reason, and does not disturb other
records. In `--dry-run` mode the entire session is rolled back at the end —
the report shows what would happen, and zero rows are written.

## Report format

```json
{
  "root": "...", "mailbox": "...", "dry_run": false,
  "counts": {"inserted": 1, "updated": 0, "skipped": 0, "errors": 0},
  "records": [{"record_key": "705DFC0E...", "status": "inserted", "reason": null}]
}
```

Exit code is non-zero only when every record failed.
