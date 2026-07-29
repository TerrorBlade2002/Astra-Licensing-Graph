# Governed document repository

The PostgreSQL catalog is the workflow authority; SharePoint is the governed binary store. Durable identity uses site, drive, drive-item, list-item, and application document keys—not display names, paths, filenames, web URLs, or temporary download URLs.

Configured purposes are `MASTER_DOCUMENTS`, `WORKING_DOCUMENTS`, `BONDS`, `SUBMITTED_FILINGS`, `LICENSES_CERTIFICATES`, `REGULATOR_CORRESPONDENCE`, `PAYMENTS_RECEIPTS`, `OFFICIAL_FORMS_CHECKLISTS`, and `QUARANTINE`. These may be separate libraries or top-level roots in one configured library.

Creation uses an explicit intent workflow: validate and hash; reject/link exact duplicates; commit an `UPLOADING` version; upload; verify size and SHA-256; persist returned identifiers; synchronize list fields; link sources; append events; make the version `AVAILABLE`. A binary is retained when later metadata synchronization fails.

Simple upload is bounded by `SHAREPOINT_SIMPLE_UPLOAD_MAX_BYTES`. Larger files use sequential 320-KiB-aligned ranges and `nextExpectedRanges`. Upload-session URLs are validated, never logged, never returned, never persisted in plaintext, and receive no Graph bearer token. Default conflicts fail; replacement needs an explicit version operation and eTag rule.

