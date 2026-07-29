"""Recurrence expansion for compliance obligations.

Every recurrence type is source-backed and explicit. There is no universal annual
date and no assumption that the NMLS renewal window applies to non-NMLS licences:
the November-1-to-December-31 company renewal period is one configurable rule
among many, keyed to jurisdictions that actually use it.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.deadlines.enums import RecurrenceType


class RecurrenceError(ValueError):
    """The recurrence configuration is unusable."""


@dataclass(frozen=True, slots=True)
class RecurrenceContext:
    """Anchors a recurrence to real dates from the licence or bond record."""

    issue_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    regulator_supplied_due_date: date | None = None
    bond_expiration_date: date | None = None
    annual_report_date: date | None = None
    last_completed_date: date | None = None
    case_event_date: date | None = None
    manual_date: date | None = None


def _safe_date(year: int, month: int, day: int) -> date:
    """Clamp to the last valid day of the month (29 Feb, 31-day rules)."""
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _next_annual(anchor_month: int, anchor_day: int, after: date, *, inclusive: bool) -> date:
    candidate = _safe_date(after.year, anchor_month, anchor_day)
    if candidate < after or (candidate == after and not inclusive):
        candidate = _safe_date(after.year + 1, anchor_month, anchor_day)
    return candidate


def next_occurrence(
    *,
    recurrence_type: str,
    config: dict[str, Any],
    context: RecurrenceContext,
    after: date,
    inclusive: bool = False,
) -> date | None:
    """Compute the next due date strictly after ``after`` (or on it if inclusive).

    Returns ``None`` when the recurrence cannot be resolved from the data
    available — a missing anchor is reported rather than guessed, so the operator
    sees "renewal with no deadline" in the data-quality report instead of a
    fabricated date.
    """
    rtype = recurrence_type

    if rtype == RecurrenceType.FIXED_ANNUAL_DATE.value:
        month, day = config.get("month"), config.get("day")
        if not isinstance(month, int) or not isinstance(day, int):
            raise RecurrenceError("FIXED_ANNUAL_DATE requires integer 'month' and 'day'.")
        return _next_annual(month, day, after, inclusive=inclusive)

    if rtype == RecurrenceType.ISSUE_ANNIVERSARY.value:
        anchor = context.issue_date or context.effective_date
        if anchor is None:
            return None
        interval = int(config.get("interval_years", 1))
        candidate = _safe_date(after.year, anchor.month, anchor.day)
        if candidate < after or (candidate == after and not inclusive):
            candidate = _safe_date(after.year + interval, anchor.month, anchor.day)
        return candidate

    if rtype == RecurrenceType.EXPIRATION_ANNIVERSARY.value:
        anchor = context.expiration_date
        if anchor is None:
            return None
        if anchor > after or (anchor == after and inclusive):
            return anchor
        interval = int(config.get("interval_years", 1))
        return _safe_date(anchor.year + interval, anchor.month, anchor.day)

    if rtype == RecurrenceType.REGULATOR_SUPPLIED.value:
        supplied = context.regulator_supplied_due_date
        if supplied is None:
            return None
        return supplied if supplied > after or (supplied == after and inclusive) else None

    if rtype == RecurrenceType.NMLS_ANNUAL_RENEWAL_WINDOW.value:
        # The NMLS company renewal period normally runs 1 Nov - 31 Dec, with
        # reinstatement possibly available in Jan/Feb depending on the regulator.
        # Modelled as configuration, never as a global default.
        end_month = int(config.get("window_end_month", 12))
        end_day = int(config.get("window_end_day", 31))
        return _next_annual(end_month, end_day, after, inclusive=inclusive)

    if rtype == RecurrenceType.BOND_EXPIRATION.value:
        anchor = context.bond_expiration_date
        if anchor is None:
            return None
        return anchor if anchor > after or (anchor == after and inclusive) else None

    if rtype == RecurrenceType.ANNUAL_REPORT_DATE.value:
        anchor = context.annual_report_date
        if anchor is not None and (anchor > after or (anchor == after and inclusive)):
            return anchor
        month, day = config.get("month"), config.get("day")
        if isinstance(month, int) and isinstance(day, int):
            return _next_annual(month, day, after, inclusive=inclusive)
        if anchor is None:
            return None
        return _safe_date(after.year + 1, anchor.month, anchor.day)

    if rtype == RecurrenceType.RELATIVE_TO_CASE_EVENT.value:
        anchor = context.case_event_date
        if anchor is None:
            return None
        offset = int(config.get("offset_days", 0))
        return anchor + timedelta(days=offset)

    if rtype == RecurrenceType.CUSTOM_INTERVAL.value:
        anchor = (
            context.last_completed_date
            or context.expiration_date
            or context.effective_date
            or context.issue_date
        )
        if anchor is None:
            return None
        months = int(config.get("interval_months", 0))
        days = int(config.get("interval_days", 0))
        if months <= 0 and days <= 0:
            raise RecurrenceError(
                "CUSTOM_INTERVAL requires a positive 'interval_months' or 'interval_days'."
            )

        candidate = anchor
        # Bounded: advance until strictly after `after`, capped to avoid a runaway
        # loop on a pathological configuration.
        for _ in range(400):
            if months:
                total = candidate.month - 1 + months
                candidate = _safe_date(candidate.year + total // 12, total % 12 + 1, candidate.day)
            if days:
                candidate = candidate + timedelta(days=days)
            if candidate > after or (candidate == after and inclusive):
                return candidate
        return None

    if rtype == RecurrenceType.MANUAL_DATE.value:
        manual = context.manual_date
        if manual is None:
            configured = config.get("date")
            if isinstance(configured, str):
                try:
                    manual = date.fromisoformat(configured)
                except ValueError as exc:
                    raise RecurrenceError(
                        f"MANUAL_DATE has an invalid date: {configured!r}"
                    ) from exc
        if manual is None:
            return None
        return manual if manual > after or (manual == after and inclusive) else None

    raise RecurrenceError(f"Unsupported recurrence type {rtype!r}.")


def expand(
    *,
    recurrence_type: str,
    config: dict[str, Any],
    context: RecurrenceContext,
    start: date,
    horizon_end: date,
    limit: int = 24,
) -> list[date]:
    """List occurrences in ``[start, horizon_end]`` up to ``limit``.

    Non-repeating recurrence types (a regulator-supplied date, a bond expiry, a
    manual date) yield at most one occurrence by design.
    """
    single_shot = {
        RecurrenceType.REGULATOR_SUPPLIED.value,
        RecurrenceType.BOND_EXPIRATION.value,
        RecurrenceType.MANUAL_DATE.value,
        RecurrenceType.RELATIVE_TO_CASE_EVENT.value,
    }
    occurrences: list[date] = []
    cursor = start
    inclusive = True
    for _ in range(limit):
        nxt = next_occurrence(
            recurrence_type=recurrence_type,
            config=config,
            context=context,
            after=cursor,
            inclusive=inclusive,
        )
        if nxt is None or nxt > horizon_end:
            break
        occurrences.append(nxt)
        if recurrence_type in single_shot:
            break
        cursor = nxt
        inclusive = False
    return occurrences


__all__ = ["RecurrenceContext", "RecurrenceError", "expand", "next_occurrence"]
