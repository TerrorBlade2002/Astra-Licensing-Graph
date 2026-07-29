# SharePoint permissions and administrator setup

Use a dedicated Entra application named **Astra Licensing Document Repository** where possible. Its Microsoft Graph application permission is **Sites.Selected** only. The repository never requests `Sites.ReadWrite.All`, `Files.ReadWrite.All`, owner, or tenant-wide access.

Administrator sequence:

1. Add Microsoft Graph application permission `Sites.Selected` and grant admin consent.
2. Create or identify the `Astra Licensing Compliance` site (`sites/AstraLicensingCompliance`).
3. Resolve its compound Graph site ID with `GET /sites/{hostname}:/sites/AstraLicensingCompliance`.
4. With an administrator identity, grant the repository service principal `write` on that site using the supported selected-permissions administration flow.
5. Verify the grant and record application ID, site ID, role, approver, and date in the change record.
6. Configure `SHAREPOINT_EXPECTED_APP_ID`, the exact site ID, and exact drive IDs in the workload environment.
7. Run `python -m app.cli.sharepoint_diagnostics`.
8. Confirm the selected site succeeds and a configured unrelated negative-test site is denied.

Administrator tokens are never application configuration. Application code does not grant permissions or change site ACLs. The optional synthetic write check is disabled by default; enable it only in staging and inspect its designated health-check folder afterward.

