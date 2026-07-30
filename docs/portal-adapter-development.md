# Portal adapter development

Portal adapters are versioned contracts, not page-scraping scripts. An adapter version must be reviewed and activated against a current portal review before a run can pin it.

Each page category has one unique fingerprint locator and explicit locators for supported fields, uploads, validation messages, and confirmation evidence. Prefer accessible role, label, test-id, or stable name locators. Generated selectors, XPath, `nth-child`, coordinate clicks, fixed sleeps, and ambiguous matches are rejected.

Adapters may navigate within the approved hostname, enter reviewed non-human fields, upload validated documents, save a draft, read values, capture validation, and recognize pages. They expose no method that can accept terms, enter MFA, solve CAPTCHA, attest, sign, authorize payment, enter payment credentials, or submit a filing.

When zero or multiple page fingerprints match, the adapter returns unknown. The worker stops, records a sanitized diagnostic hash, marks the run `FAILED_REVIEW`, and creates an `UNEXPECTED_PAGE` handoff. Update and approve a new adapter version; do not weaken the old contract.

Use only local fixtures:

```powershell
python -m app.cli.portal_adapter_test --portal-key <PORTAL_KEY> --fixture tests/fixtures/portals/field.html
```

The command refuses non-local fixture URLs. Never run adapter tests against NMLS or a regulator portal.

