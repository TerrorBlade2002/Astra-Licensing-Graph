"""Business-day and holiday arithmetic.

Deliberately *not* applied by default. Many regulators treat a statutory date as
fixed even when it falls on a weekend, so shifting every due date to the next
business day would invent deadlines that do not exist. Each deadline rule declares
its own :class:`~app.deadlines.enums.AdjustmentPolicy`, and only rules whose policy
is source-backed shift anything.

Federal holidays are computed rather than hard-coded per year so the calendar
stays correct without annual maintenance. Jurisdiction-specific holidays layer on
top via an explicit calendar mapping.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from app.deadlines.enums import AdjustmentPolicy

WEEKEND = (5, 6)  # Saturday, Sunday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` of a month (1-indexed)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The final ``weekday`` of a month."""
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """Federal observation rule: Saturday holidays shift back, Sunday forward."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=64)
def us_federal_holidays(year: int) -> frozenset[date]:
    """US federal holidays for ``year``, including observed weekday shifts."""
    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),  # Independence Day
        date(year, 11, 11),  # Veterans Day
        date(year, 12, 25),  # Christmas Day
    ]
    floating = [
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday(year, 5, 0),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    ]
    return frozenset([_observed(day) for day in fixed] + floating)


class BusinessCalendar:
    """Weekend and holiday calendar for one jurisdiction.

    ``extra_holidays`` carries jurisdiction-specific closures (a state holiday, a
    regulator's published closure). ``observe_federal`` can be disabled for a
    jurisdiction that does not follow the federal calendar.
    """

    def __init__(
        self,
        *,
        extra_holidays: frozenset[date] | set[date] | None = None,
        observe_federal: bool = True,
        weekend: tuple[int, ...] = WEEKEND,
    ) -> None:
        self.extra_holidays = frozenset(extra_holidays or ())
        self.observe_federal = observe_federal
        self.weekend = weekend

    def is_holiday(self, day: date) -> bool:
        if day in self.extra_holidays:
            return True
        return self.observe_federal and day in us_federal_holidays(day.year)

    def is_business_day(self, day: date) -> bool:
        return day.weekday() not in self.weekend and not self.is_holiday(day)

    def next_business_day(self, day: date, *, inclusive: bool = True) -> date:
        candidate = day if inclusive else day + timedelta(days=1)
        # Bounded loop: at most a week of weekend plus consecutive holidays.
        for _ in range(30):
            if self.is_business_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        return candidate

    def previous_business_day(self, day: date, *, inclusive: bool = True) -> date:
        candidate = day if inclusive else day - timedelta(days=1)
        for _ in range(30):
            if self.is_business_day(candidate):
                return candidate
            candidate -= timedelta(days=1)
        return candidate

    def add_business_days(self, day: date, count: int) -> date:
        """Move ``count`` business days forward (or backward when negative)."""
        if count == 0:
            return self.next_business_day(day)
        step = 1 if count > 0 else -1
        remaining = abs(count)
        candidate = day
        while remaining:
            candidate += timedelta(days=step)
            if self.is_business_day(candidate):
                remaining -= 1
        return candidate

    def apply_adjustment(self, day: date, policy: str) -> tuple[date, str | None]:
        """Apply an adjustment policy. Returns ``(date, applied_policy_or_None)``.

        ``NONE`` returns the date untouched, which is the correct default for a
        statutory deadline. ``MANUAL_REVIEW`` also returns it untouched but reports
        the policy so the caller can flag it for a human instead of guessing.
        """
        if policy == AdjustmentPolicy.NONE.value or self.is_business_day(day):
            return day, None
        if policy == AdjustmentPolicy.NEXT_BUSINESS_DAY.value:
            return self.next_business_day(day, inclusive=False), policy
        if policy == AdjustmentPolicy.PREVIOUS_BUSINESS_DAY.value:
            return self.previous_business_day(day, inclusive=False), policy
        if policy == AdjustmentPolicy.JURISDICTION_SPECIFIC.value:
            # Without a jurisdiction-specific override loaded, the safe reading is
            # "do not move the date"; the rule owner must supply the calendar.
            return day, policy
        if policy == AdjustmentPolicy.MANUAL_REVIEW.value:
            return day, policy
        return day, None


DEFAULT_CALENDAR = BusinessCalendar()


__all__ = [
    "DEFAULT_CALENDAR",
    "WEEKEND",
    "BusinessCalendar",
    "us_federal_holidays",
]
