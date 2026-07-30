# Licensing operations runbook

- Stale source: register a fresh snapshot, compare, review, create a new rule-set
  version if affected, regress, then activate.
- Duplicate license: determine correct authority/entity, preserve status events,
  and retire the incorrect duplicate with documented evidence.
- Incorrect entity: never reassign governed evidence silently; create/correct the
  scoped record and document the reconciliation.
- Missed renewal or overdue case: materialize dates, open/escalate the case,
  record reason, and use the controlled communication workflow for outreach.
- Missing document: upload/promote into governed storage, complete metadata and
  approval, then create a new packet version.
- Stale answer: expire it, request the owner’s current answer, approve a new
  version, and regenerate affected forms.
- Invalid form: preserve the template, reject the instance, inspect/register a
  corrected version, and rebuild.
- Wrong packet: reject if still mutable; if approved, create a new version.
- Deadline override: manager records the new date and substantive reason.
- Case reopening: create a follow-on obligation/case or use an allowed transition;
  do not rewrite append-only history.

Run `python -m app.cli.licensing_data_quality run` after reconciliation.

Run the durable Milestone 6 queues separately from the Graph and communication
queues:

```powershell
python -m app.workers.runner --queues licensing,requirements,deadlines,packets,forms,imports
python -m app.workers.scheduling
```

The scheduler uses time-bucketed idempotency keys for deadline materialization,
license-renewal checks, document expiry, and information freshness. Packet ZIP
generation is queued after the manifest is built. Approval remains unavailable
until the worker has downloaded every pinned SharePoint version, rechecked its
SHA-256 digest, and stored the archive behind a governed storage URI.
