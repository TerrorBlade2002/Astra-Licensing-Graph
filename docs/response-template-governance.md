# Response-template governance

Templates have a stable key and immutable versions. Versions move from `DRAFT` to `ACTIVE` to `RETIRED`; activating a version retires the previous active version. An active version cannot be edited—create a new version instead.

Allowed variables are limited in code to the approved licensing field registry: vendor, jurisdiction, license identifiers, verified requested items, due date, owner, licensing mailbox, approved document list, legal entity, and response reference. Admins cannot introduce arbitrary variable names. Calls, object traversal, indexing, imports, includes, filesystem access, environment access, and arbitrary filters are rejected.

Rendering fails on undefined variables, `[TODO]`, `<insert value>`, unresolved Jinja syntax, empty content, or an attachment claim without selected attachments. The application supplies authoritative values from the reviewed task/classification; browser values cannot replace them. Template activation must be regression-tested with synthetic values and audited by the approving administrator.
