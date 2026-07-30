# Deadline engine

Deadline rules support fixed dates, issue/expiration anniversaries, supplied
regulator dates, NMLS windows, bond expiry, annual reports, relative case dates,
custom recurrence, and manual dates. Source-backed jurisdiction/license-specific
rules win over defaults.

The default preparation lead is configurable and is not a universal legal
deadline. Each rule explicitly selects no adjustment, previous/next business
day, jurisdiction-specific adjustment, or manual review. The engine never
assumes a weekend or holiday moves a statutory date.

Materialization creates concrete, idempotently keyed deadlines for the planning
horizon. Internal milestones can cover vendor outreach, information, documents,
forms, signature, submission, and follow-up. Overrides detach a date from its
materialization key, require a reason, and append a deadline event.

Escalation windows and recipients are policy driven. Portal notifications and
outbox events are idempotent; no external email is sent.
