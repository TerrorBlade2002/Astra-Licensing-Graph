"""Escalation ladder for approaching and overdue deadlines.

Escalation is *idempotent by level*: a deadline records the highest level already
notified, so a sweep running hourly does not re-page an owner every hour. Only
crossing into a new window produces a new notification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.deadlines.enums import DeadlineSeverity, EscalationLevel
from app.deadlines.rules import DEFAULT_ESCALATION_LADDER

#: Overdue ladder: days *past* due -> level. Overdue escalation climbs faster than
#: pre-due warning because the regulatory exposure is already live.
DEFAULT_OVERDUE_LADDER: dict[int, str] = {
    0: EscalationLevel.MANAGER.value,
    3: EscalationLevel.MANAGER.value,
    7: EscalationLevel.COUNSEL.value,
    14: EscalationLevel.EXECUTIVE.value,
}

_LEVEL_ORDER = {
    EscalationLevel.OWNER.value: 1,
    EscalationLevel.BACKUP_OWNER.value: 2,
    EscalationLevel.REVIEWER.value: 3,
    EscalationLevel.MANAGER.value: 4,
    EscalationLevel.COUNSEL.value: 5,
    EscalationLevel.EXECUTIVE.value: 6,
}


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    """What (if anything) should be notified for one deadline right now."""

    should_notify: bool
    level: str | None
    window_days: int | None
    days_remaining: int
    is_overdue: bool
    severity: str
    reason: str

    @property
    def notification_key_suffix(self) -> str:
        """Stable suffix so the same window never notifies twice."""
        if self.is_overdue:
            return f"overdue-{self.window_days}"
        return f"upcoming-{self.window_days}"


def level_rank(level: str | None) -> int:
    return _LEVEL_ORDER.get(level or "", 0)


def evaluate_escalation(
    *,
    due_at: datetime,
    last_escalation_level: str | None = None,
    ladder: dict[int, str] | None = None,
    overdue_ladder: dict[int, str] | None = None,
    overdue_enabled: bool = True,
    now: datetime | None = None,
) -> EscalationDecision:
    """Decide whether this deadline has crossed into a new escalation window."""
    moment = now or datetime.now(tz=UTC)
    upcoming = ladder or DEFAULT_ESCALATION_LADDER
    overdue = overdue_ladder or DEFAULT_OVERDUE_LADDER

    delta_days = (due_at.date() - moment.date()).days

    if delta_days < 0:
        if not overdue_enabled:
            return EscalationDecision(
                should_notify=False,
                level=None,
                window_days=None,
                days_remaining=delta_days,
                is_overdue=True,
                severity=DeadlineSeverity.REGULATORY_RISK.value,
                reason="Overdue escalation is disabled by configuration.",
            )
        days_past = abs(delta_days)
        crossed = [threshold for threshold in sorted(overdue) if days_past >= threshold]
        if not crossed:
            return EscalationDecision(
                should_notify=False,
                level=None,
                window_days=None,
                days_remaining=delta_days,
                is_overdue=True,
                severity=DeadlineSeverity.REGULATORY_RISK.value,
                reason="No overdue threshold reached.",
            )
        threshold = crossed[-1]
        level = overdue[threshold]
        # Only notify when this represents a genuine escalation beyond the last.
        should = level_rank(level) > level_rank(last_escalation_level)
        return EscalationDecision(
            should_notify=should,
            level=level,
            window_days=threshold,
            days_remaining=delta_days,
            is_overdue=True,
            severity=DeadlineSeverity.REGULATORY_RISK.value,
            reason=(
                f"Overdue by {days_past} day(s); escalating to {level}."
                if should
                else f"Already escalated to {last_escalation_level}."
            ),
        )

    # Not yet due: find the tightest window already entered.
    entered = [window for window in sorted(upcoming) if delta_days <= window]
    if not entered:
        return EscalationDecision(
            should_notify=False,
            level=None,
            window_days=None,
            days_remaining=delta_days,
            is_overdue=False,
            severity=DeadlineSeverity.INFORMATIONAL.value,
            reason="Outside every alert window.",
        )
    window = entered[0]
    level = upcoming[window]
    should = level_rank(level) > level_rank(last_escalation_level)
    severity = (
        DeadlineSeverity.CRITICAL.value
        if delta_days <= 3
        else DeadlineSeverity.IMPORTANT.value
        if delta_days <= 14
        else DeadlineSeverity.NORMAL.value
    )
    return EscalationDecision(
        should_notify=should,
        level=level,
        window_days=window,
        days_remaining=delta_days,
        is_overdue=False,
        severity=severity,
        reason=(
            f"{delta_days} day(s) remaining; entered the {window}-day window for {level}."
            if should
            else f"Already notified at or above {last_escalation_level}."
        ),
    )


def resolve_recipient(
    *,
    level: str,
    owner: str | None,
    backup_owner: str | None,
    reviewer: str | None = None,
    manager: str | None = None,
    counsel: str | None = None,
    executive: str | None = None,
) -> str | None:
    """Map an escalation level to a concrete actor, falling back up the chain.

    Falling back matters: an unassigned deadline must still reach somebody rather
    than silently escalating into the void.
    """
    chain: dict[str, list[str | None]] = {
        EscalationLevel.OWNER.value: [owner, backup_owner, manager],
        EscalationLevel.BACKUP_OWNER.value: [backup_owner, owner, manager],
        EscalationLevel.REVIEWER.value: [reviewer, manager, owner],
        EscalationLevel.MANAGER.value: [manager, reviewer, owner],
        EscalationLevel.COUNSEL.value: [counsel, manager],
        EscalationLevel.EXECUTIVE.value: [executive, manager, counsel],
    }
    for candidate in chain.get(level, [owner]):
        if candidate:
            return candidate
    return None


__all__ = [
    "DEFAULT_OVERDUE_LADDER",
    "EscalationDecision",
    "evaluate_escalation",
    "level_rank",
    "resolve_recipient",
]
