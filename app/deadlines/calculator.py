"""Deadline calculation: statutory anchors plus derived internal milestones.

The distinction this module enforces is the one that matters operationally:

* A **statutory** deadline comes from a source-backed rule. It is adjusted only
  when that rule says so, and its date is never moved for convenience.
* An **internal** milestone is ours. It may be shifted onto a business day freely,
  because missing an internal target is a scheduling problem, not a filing default.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.deadlines.business_days import DEFAULT_CALENDAR, BusinessCalendar
from app.deadlines.enums import (
    INTERNAL_DEADLINE_TYPES,
    AdjustmentPolicy,
    DeadlineSeverity,
    DeadlineStatus,
    DeadlineType,
)
from app.deadlines.recurrence import RecurrenceContext, expand
from app.deadlines.rules import DeadlinePolicy

#: Hour of day (local to the jurisdiction) used as the nominal cut-off. Regulators
#: rarely publish a clock time; end of business is the safe operational reading.
DEFAULT_DUE_HOUR = 17


def _zone(timezone_name: str | None) -> tzinfo:
    if not timezone_name:
        return UTC
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        # An unknown timezone must not break materialization; UTC keeps ordering
        # correct and the discrepancy shows up in the data-quality report.
        return UTC


def to_due_datetime(
    day: date, *, timezone_name: str | None, hour: int = DEFAULT_DUE_HOUR
) -> datetime:
    """Convert a calendar date into an instant at end-of-business, then to UTC.

    Storing UTC keeps ordering and comparison correct; the jurisdiction timezone is
    what makes "due today" mean the same thing to an operator in any office.
    """
    local = datetime.combine(day, time(hour=hour, minute=0), tzinfo=_zone(timezone_name))
    return local.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PlannedDeadline:
    """A calculated deadline, not yet persisted."""

    deadline_type: str
    due_at: datetime
    due_date: date
    severity: str
    internal_target_at: datetime | None = None
    applied_adjustment: str | None = None
    source_rule_id: uuid.UUID | None = None
    materialization_key: str | None = None
    status: str = DeadlineStatus.SCHEDULED.value
    #: Set when the rule demands a human look at the date rather than shifting it.
    needs_manual_review: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def _severity_for(deadline_type: str, days_until: int) -> str:
    """Severity rises as a date nears; statutory dates outrank internal ones."""
    statutory = deadline_type not in INTERNAL_DEADLINE_TYPES
    if days_until < 0:
        return (
            DeadlineSeverity.REGULATORY_RISK.value if statutory else DeadlineSeverity.CRITICAL.value
        )
    if days_until <= 3:
        return DeadlineSeverity.CRITICAL.value if statutory else DeadlineSeverity.IMPORTANT.value
    if days_until <= 14:
        return DeadlineSeverity.IMPORTANT.value if statutory else DeadlineSeverity.NORMAL.value
    if days_until <= 60:
        return DeadlineSeverity.NORMAL.value
    return DeadlineSeverity.INFORMATIONAL.value


def build_materialization_key(
    *,
    obligation_id: uuid.UUID,
    deadline_type: str,
    due_date: date,
    rule_id: uuid.UUID | None,
) -> str:
    """Deterministic key making repeated materialization idempotent.

    Hashed so the key stays a fixed length regardless of input, and stable so the
    same (obligation, type, date, rule) always collides on the unique index rather
    than inserting a duplicate.
    """
    raw = f"{obligation_id}|{deadline_type}|{due_date.isoformat()}|{rule_id or 'no-rule'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_deadlines(
    *,
    obligation_id: uuid.UUID,
    obligation_type: str,
    policy: DeadlinePolicy | None,
    context: RecurrenceContext,
    horizon_start: date,
    horizon_end: date,
    default_lead_days: int,
    timezone_name: str | None = None,
    calendar: BusinessCalendar | None = None,
    statutory_deadline_type: str = DeadlineType.STATUTORY_DUE.value,
    today: date | None = None,
    max_occurrences: int = 6,
) -> list[PlannedDeadline]:
    """Produce statutory and internal deadlines for one obligation.

    Returns an empty list when no due date can be derived. That silence is
    intentional: a renewal with no resolvable deadline is surfaced by the
    data-quality report rather than papered over with an invented date.
    """
    if policy is None:
        return []

    cal = calendar or DEFAULT_CALENDAR
    reference = today or date.today()
    planned: list[PlannedDeadline] = []

    occurrences = expand(
        recurrence_type=policy.recurrence_type,
        config=policy.recurrence_config,
        context=context,
        start=horizon_start,
        horizon_end=horizon_end,
        limit=max_occurrences,
    )

    lead = policy.lead_time_days if policy.lead_time_days is not None else default_lead_days
    offsets = policy.offsets(default_lead_days=default_lead_days)

    for occurrence in occurrences:
        adjusted, applied = cal.apply_adjustment(occurrence, policy.adjustment_policy)
        notes: list[str] = []
        needs_review = applied == AdjustmentPolicy.MANUAL_REVIEW.value
        if needs_review:
            notes.append(
                "The statutory date falls on a non-business day and the rule "
                "requires manual confirmation of the effective due date."
            )
        if applied == AdjustmentPolicy.JURISDICTION_SPECIFIC.value:
            notes.append(
                "Jurisdiction-specific adjustment is configured but no jurisdiction "
                "calendar was supplied; the unadjusted date was kept."
            )
            needs_review = True

        statutory_days = (adjusted - reference).days
        planned.append(
            PlannedDeadline(
                deadline_type=statutory_deadline_type,
                due_at=to_due_datetime(adjusted, timezone_name=timezone_name),
                due_date=adjusted,
                severity=_severity_for(statutory_deadline_type, statutory_days),
                internal_target_at=(
                    to_due_datetime(adjusted - timedelta(days=lead), timezone_name=timezone_name)
                    if lead > 0
                    else None
                ),
                applied_adjustment=applied,
                source_rule_id=policy.id,
                materialization_key=build_materialization_key(
                    obligation_id=obligation_id,
                    deadline_type=statutory_deadline_type,
                    due_date=adjusted,
                    rule_id=policy.id,
                ),
                needs_manual_review=needs_review,
                notes=tuple(notes),
            )
        )

        # Internal milestones hang off the statutory date and may always move onto
        # a business day, since they bind only our own staff.
        for deadline_type, offset in sorted(offsets.items(), key=lambda kv: -kv[1]):
            target = adjusted - timedelta(days=offset)
            if target > horizon_end:
                continue
            shifted = cal.next_business_day(target) if not cal.is_business_day(target) else target
            planned.append(
                PlannedDeadline(
                    deadline_type=deadline_type,
                    due_at=to_due_datetime(shifted, timezone_name=timezone_name),
                    due_date=shifted,
                    severity=_severity_for(deadline_type, (shifted - reference).days),
                    internal_target_at=to_due_datetime(shifted, timezone_name=timezone_name),
                    applied_adjustment=(
                        AdjustmentPolicy.NEXT_BUSINESS_DAY.value if shifted != target else None
                    ),
                    source_rule_id=policy.id,
                    materialization_key=build_materialization_key(
                        obligation_id=obligation_id,
                        deadline_type=deadline_type,
                        due_date=shifted,
                        rule_id=policy.id,
                    ),
                )
            )

    return planned


def classify_status(
    *, due_at: datetime, now: datetime | None = None, approaching_days: int = 30
) -> str:
    """Derive a display status from a due instant."""
    moment = now or datetime.now(tz=UTC)
    if due_at < moment:
        return DeadlineStatus.OVERDUE.value
    if due_at.date() == moment.date():
        return DeadlineStatus.DUE_TODAY.value
    if (due_at - moment).days <= approaching_days:
        return DeadlineStatus.APPROACHING.value
    return DeadlineStatus.SCHEDULED.value


__all__ = [
    "DEFAULT_DUE_HOUR",
    "PlannedDeadline",
    "build_materialization_key",
    "classify_status",
    "plan_deadlines",
    "to_due_datetime",
]
