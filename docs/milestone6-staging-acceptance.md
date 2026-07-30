# Milestone 6 staging acceptance

Use synthetic entities, people, documents, license numbers, and regulator data.
Do not configure live portal credentials or production Microsoft tenants.

1. Import a synthetic XLSX tracker, map columns, dry run, resolve one duplicate,
   apply, and reconcile inventory/obligations.
2. Create two entities with similarly named licenses; prove documents and
   answers cannot cross entity boundaries.
3. Evaluate three jurisdictions and verify required/possible/counsel outcomes,
   citations, missing facts, separate NMLS/outside channels, and no auto-created
   license.
4. Materialize a 30-day renewal and a bond renewal; open cases, record questions,
   approve answers, and reach document checklist.
5. Approve a synthetic reusable answer, use it, expire it, and verify the next
   form creates an information request.
6. Build a three-document packet with one expired document, replace it, verify
   IDs/hashes/manifest, wait for the worker-created governed ZIP, approve and
   download it, then prove it is immutable.
7. Inspect a synthetic AcroForm, map fields, generate a draft with one signature
   field blank, activate the pinned template, wait for the generated governed
   draft, approve the exact hash, and record a separately uploaded signed copy.
8. Record synthetic external submission evidence, link renewed evidence, update
   inventory, generate the next obligation, complete the case, and inspect the
   full audit timeline.

Confirm throughout: no NMLS/state login, portal form entry, signature injection,
attestation, fee payment, external transmission, or filing submission occurred.
Also inspect structured logs and CI artifacts for restricted values, temporary
Graph URLs, and any non-local licensing-regulator hostname.
