# Document taxonomy and SharePoint metadata

`DocumentType` is centralized in `app/documents/enums.py` and stored as text so new business taxonomy values do not require PostgreSQL enum migrations. Workflow states remain constrained.

Libraries should expose the `Astra*` columns listed in `app/documents/metadata.py`. Bootstrap discovers the backing list and maps each display name to its actual SharePoint internal name. It reports missing/incompatible columns and never silently recreates a conflicting column.

Columns contain operational metadata only: document key/type/status, confidentiality, entity, jurisdiction, license/vendor dates, reuse flags, SHA-256, source type, and internal source IDs. Email bodies, secrets, tokens, SSNs, account numbers, and file content are prohibited.

Canonical names follow `{entity}_{jurisdiction}_{type}_{date}_{short-id}.{ext}` after Unicode normalization, separator/control-character removal, reserved-name defense, trusted-extension validation, and length limiting. The original filename remains in PostgreSQL.

