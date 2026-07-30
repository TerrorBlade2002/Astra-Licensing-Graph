# Business UAT checklist (Milestone 8)

Run in **staging**, with business users, before the pilot. Use synthetic or
approved test data; send email only to approved internal recipients; use the
synthetic portal or a formally approved test portal.

Copy this table into a spreadsheet or fill it in place — either is fine, and it
stays in version control. There is no UAT application to build.

For every scenario record: tester, expected result, actual result, issue,
pass/fail, and evidence (screenshot, case key, or audit event ID).

| # | Scenario | Expected result | Tester | Actual result | Issue | Pass/Fail | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Licence renewal** — a licence approaching expiry | An obligation and deadline exist, a renewal case opens at the configured lead time, and the case shows the right entity, jurisdiction, and licence type | | | | | |
| 2 | **Bond or annual report** — open the case for a bond renewal or annual report | The correct obligation type, due date, and owner appear; the case follows the documented stages | | | | | |
| 3 | **Vendor information request** — a vendor email asking for information | The email is classified, reviewed, and a task with the requested items is created | | | | | |
| 4 | **Reusable information answer** — answer a request from the registry | The approved value is reused, provenance is shown, restricted values stay masked, and a stale value is refused | | | | | |
| 5 | **Document packet** — build a packet for the case | The packet contains the correct entity's current approved document versions, and missing items are listed rather than silently omitted | | | | | |
| 6 | **Form with missing fields** — prepare a form that lacks data | The form is marked missing-information, lists exactly which fields are missing, and is not treated as ready | | | | | |
| 7 | **Controlled email response** — draft, review, approve, send | The draft is reviewed, a *different* authorized approver approves, the test email is sent to an approved internal recipient, the sent copy is reconciled, and the original message is moved | | | | | |
| 8 | **Upcoming-deadline alert** — check the calendar and alerts | The deadline appears in the right alert window with the right owner and severity | | | | | |
| 9 | **Portal-assisted workflow** (only where approved) — run an approved portal run | The system prepares approved values and documents, stops for login, MFA, CAPTCHA, attestation, payment, and Submit; the human performs the final action; confirmation evidence is recorded | | | | | |
| 10 | **Renewed licence updates the inventory** — record the renewal outcome | The licence shows the new expiration and renewal date, history records the change, and the next obligation is created | | | | | |

## Rules during UAT

- Human review stays mandatory; do not disable it to speed a scenario up.
- Do not send to an external recipient.
- Do not use a real regulator or vendor portal account.
- Log every defect with the case key and correlation ID; retest after the fix.

## Sign-off

| Item | Value |
| --- | --- |
| Scenarios executed | / 10 |
| Failures found | |
| Failures fixed and retested | |
| Business sign-off (name, date) | |
| Process-owner approval to start the pilot (name, date) | |
