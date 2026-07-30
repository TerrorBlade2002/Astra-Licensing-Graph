# Portal automation governance

Milestone 7 provides human-supervised preparation and portal assistance. It does not provide unattended filing.

Every run pins a portal definition, an approved review version, an active adapter version, a filing type, and a legal entity. Before every browser job, Astra revalidates the portal status, review dates, terms-review expiry, filing/entity scope, approved automation level, and the assigned operator's authorization. A suspension, expiry, or revocation stops further work.

Portal reviews explicitly list allowed and prohibited actions. Terms acceptance, MFA entry, CAPTCHA handling, attestation, signature, payment authorization, payment credential entry, and final submission are absolute human-only actions regardless of a review's contents. `AUTOMATION_PROHIBITED` portals cannot activate an adapter or start a run.

Automation levels are ordered:

1. `PREPARE_ONLY`
2. `NAVIGATION_ASSIST`
3. `ASSISTED_ENTRY`
4. `UPLOAD_ASSIST`
5. `PRE_SUBMISSION_ASSIST`
6. `API_ASSISTED`

A run may never exceed the portal's approved level. An official-API adapter accepts only reviewed draft, upload, read, and validation routes; final-action routes are rejected.

Portal definitions, reviews, adapters, field mappings, and user authorizations are managed through `/api/v1/portals`. Approval, adapter activation, and authorization changes are auditable licensing events.

