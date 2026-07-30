# Go-live checklist

For the licensing process owner and the deploying engineer. Work top to bottom;
do not start a section until the previous one is signed. Record real dates and
names — an unsigned line means the step did not happen.

Technical detail lives in [DEPLOYMENT.md](DEPLOYMENT.md).

| Field | Value |
| --- | --- |
| Process owner | |
| Deploying engineer | |
| Target go-live date | |
| Approved domains | `api.<domain>` / `licensing.<domain>` |

---

## 1. Migration

| # | Step | Command / evidence | Done | By | Date |
| --- | --- | --- | --- | --- | --- |
| 1.1 | Obtain the approved master tracker and supporting files from the process owner | file name + SHA-256 | ☐ | | |
| 1.2 | Store an untouched copy in the governed repository | document ID | ☐ | | |
| 1.3 | Record source counts (entities, licences, bonds, annual reports, open cases) in `expected-counts.json` | file | ☐ | | |
| 1.4 | Dry run in **staging** | `python -m app.cli.import_master_tracker plan --file <file> --mapping <map.json>` | ☐ | | |
| 1.5 | Review insert / update / skip / conflict / error counts | plan output | ☐ | | |
| 1.6 | Resolve every conflict and error manually (fix source data or mapping) | notes | ☐ | | |
| 1.7 | Repeat the dry run until only expected actions remain | plan output | ☐ | | |
| 1.8 | Production dry run | same command, production environment | ☐ | | |
| 1.9 | Apply in production | `python -m app.cli.import_master_tracker run --file <file> --mapping <map.json> --confirm` | ☐ | | |
| 1.10 | Re-run the same import to confirm idempotency (expect only `skip`) | plan output | ☐ | | |
| 1.11 | Import bonds, annual reports, renewal dates, open cases, approved information, approved documents, responsible owners | per-source notes | ☐ | | |

Nothing in the importer invents a legal entity, jurisdiction, or licence type:
unresolved names are errors to fix at source, never guesses.

## 2. Reconciliation

```bash
python -m app.cli.migration_reconcile check --expected expected-counts.json
```

Exits non-zero on any mismatch. Record the actual numbers:

| Metric | Source count | System count | Match | Note |
| --- | --- | --- | --- | --- |
| Legal entities | | | ☐ | |
| Active licences | | | ☐ | |
| Licences expiring within 120 days | | | ☐ | |
| Bonds | | | ☐ | |
| Annual reports | | | ☐ | |
| Open cases | | | ☐ | |
| Overdue items | | | ☐ | |
| Licences missing a renewal date | | | ☐ | |

Also run `python -m app.cli.licensing_data_quality run` and clear or accept
every ERROR finding.

Process-owner approval of the migrated data: __________________ (name, date)

## 3. UAT

Complete [docs/uat-checklist.md](docs/uat-checklist.md) in **staging** with
business users. Every scenario needs a tester, expected result, actual result,
pass/fail, and evidence.

- [ ] All ten scenarios executed
- [ ] Every failure fixed and retested
- [ ] UAT sheet stored with this checklist
- [ ] Business sign-off: __________________ (name, date)

## 4. Pilot

Run [docs/pilot-checklist.md](docs/pilot-checklist.md): one legal entity, a
small set of licences, one vendor, selected users, at most one approved portal.

- [ ] Pilot scope agreed and recorded
- [ ] Manual tracker kept in parallel for the whole pilot
- [ ] System deadlines compared with manual deadlines — no unexplained difference
- [ ] Every classification reviewed
- [ ] Every outbound email reviewed and approved before sending
- [ ] Every filing submitted by a human
- [ ] No stop condition triggered (or: triggered, fixed, and re-run)
- [ ] Pilot sign-off: __________________ (name, date)

## 5. Approvals before go-live

- [ ] Railway production services running (`backend`, `frontend`, `worker`,
      `scheduler`, Postgres; `browser-worker` only if approved)
- [ ] Production variables configured; `python -m app.cli.check_deployment` passes
- [ ] Database migration succeeded
- [ ] Scheduled backups enabled
- [ ] Restore test completed — date: __________
- [ ] Master tracker migrated and reconciled (sections 1–2)
- [ ] Entra sign-in works for each role
- [ ] Graph mailbox access verified
- [ ] SharePoint access verified
- [ ] UAT passed (section 3)
- [ ] Pilot passed (section 4)
- [ ] Security checklist in DEPLOYMENT.md section 13 completed
- [ ] Support contacts recorded (below)
- [ ] Rollback instructions read by the on-call engineer

## 6. Go-live sequence

Enable one step at a time and watch `/api/v1/operations/status` between steps.

| # | Step | Flag / action | Done |
| --- | --- | --- | --- |
| 1 | Deploy backend, frontend, worker, scheduler, database | Railway | ☐ |
| 2 | Confirm health checks | `/health/ready`, `/api/v1/operations/status` | ☐ |
| 3 | Confirm migration | `/api/v1/system/version` shows the expected revision | ☐ |
| 4 | Import approved production data | section 1 | ☐ |
| 5 | Reconcile totals | section 2 | ☐ |
| 6 | Enable mailbox ingestion | `GRAPH_ENABLED=true` | ☐ |
| 7 | Enable classification with mandatory review | `CLASSIFICATION_ENABLED=true`, `CLASSIFICATION_REVIEW_REQUIRED=true` | ☐ |
| 8 | Enable tasks, documents, packets, forms | `SHAREPOINT_ENABLED`, `PACKET_GENERATION_ENABLED`, `FORM_PREPARATION_ENABLED` | ☐ |
| 9 | Enable controlled drafting | `COMMUNICATIONS_ENABLED=true`, `GRAPH_DRAFT_CREATION_ENABLED=true` | ☐ |
| 10 | Send-approval test, then enable sending | `GRAPH_SEND_ENABLED=true` after a successful approved test send | ☐ |
| 11 | Enable portal assistance for approved portals only | `PORTAL_AUTOMATION_ENABLED`, `BROWSER_AUTOMATION_ENABLED`, `PORTAL_ALLOWED_HOSTS` | ☐ |
| 12 | Monitor the first real cases daily for two weeks | status endpoint + case review | ☐ |

Steps 6–11 are deliberately separate deployments. Do not enable them together.

## 7. Rollback

1. Disable processing flags (`GRAPH_SEND_ENABLED`,
   `GRAPH_DRAFT_CREATION_ENABLED`, `GRAPH_MESSAGE_MOVE_ENABLED`,
   `CLASSIFICATION_AUTO_ENQUEUE`, `PORTAL_AUTOMATION_ENABLED`,
   `BROWSER_AUTOMATION_ENABLED`).
2. Stop `worker`, `scheduler`, and `browser-worker`; leave the portal readable.
3. Redeploy the last working Railway deployment.
4. Restore the database only if data is wrong (DEPLOYMENT.md section 9).
5. Resume the manual tracker and notify the licensing team.

## 8. Contacts

| Role | Name | Contact | Hours |
| --- | --- | --- | --- |
| Licensing process owner | | | |
| Deploying engineer / on-call | | | |
| Microsoft 365 administrator | | | |
| Railway account owner | | | |
| Legal / compliance escalation | | | |

## 9. Standing constraints

These do not change at go-live and are not configurable away:

- Every classification result is reviewed by a person.
- Every outbound email requires an approval by someone other than the drafter.
- Every regulator or vendor filing is submitted by a person.
- Signatures, attestations, payments, MFA, and CAPTCHA are human-only.
- Cross-entity reuse of documents and information stays blocked.
