# Milestone 7 staging acceptance

Use only the synthetic local portal and synthetic identities. Do not configure NMLS, regulator, vendor, payment, Microsoft production, or public portal credentials.

1. Apply the migration and verify all 15 Milestone 7 tables and indexes.
2. Confirm production configuration rejects disabled human-only controls, CAPTCHA solving, MFA bypass, public remote debugging, unencrypted persistence, development authentication, and an empty allowlist.
3. Register a localhost test portal; create and approve a scoped review; create and activate a fixture-tested adapter.
4. Authorize two synthetic users for one entity and filing type. Confirm another entity, filing type, expired review, revoked user, prohibited portal, and higher automation level are blocked.
5. Start two browser sessions and confirm separate contexts, owners, profiles, expiry, cleanup, and no persisted state.
6. Exercise login, MFA, CAPTCHA, terms, sensitive-field, attestation, payment, and final-submit handoffs. Confirm no worker lease remains held and another user cannot reuse the session.
7. Enter synthetic approved values and upload synthetic approved documents. Confirm stale, expired, quarantined, superseded, wrong-entity, wrong-category, oversized, and hash-invalid documents are blocked.
8. Trigger a validation discrepancy, correct its approved source, and verify the old snapshot approval is invalidated.
9. Approve a new exact snapshot with a distinct reviewer.
10. Complete attestation and payment through the dedicated human controls. Confirm no secret, signature, payment credential, or full attestation text is stored.
11. Have the assigned person perform the synthetic final action and record confirmation evidence. Confirm the case reaches submitted-to-regulator/vendor, a follow-up is created, and the license is not marked renewed.
12. Repeat with an ambiguous result. Confirm no final-submit retry is queued and reconciliation is the only next action.
13. Change a page fingerprint. Confirm the adapter stops with `FAILED_REVIEW` and retains only a sanitized diagnostic hash.
14. Inspect logs, artifacts, database rows, and temporary storage for passwords, MFA codes, cookies, tokens, browser state, CAPTCHA content, payment details, unrestricted values, and live portal hostnames.

Record migration, Ruff, mypy, backend test, frontend typecheck/lint/test/build, synthetic Playwright, mocked end-to-end, and coverage results only when those commands have actually been executed.

