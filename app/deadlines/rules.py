"""Deadline-rule value objects and configuration validation.

Separating the rule shape from the ORM lets the calculator be exercised with plain
data and keeps JSONB payload validation in one place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.deadlines.enums import (
    DEFAULT_ALERT_WINDOWS,
    AdjustmentPolicy,
    DeadlineType,
    EscalationLevel,
    RecurrenceType,
)

#: Default internal milestone offsets, expressed as days *before* the statutory
#: date. These mirror the real process: contact the vendor early, chase answers,
#: gather documents, complete forms, obtain signature, submit with slack left.
#: They are defaults only — a jurisdiction-specific, source-backed rule overrides
#: them, and the whole ladder scales down when the lead time is short.
DEFAULT_MILESTONE_OFFSETS: dict[str, int] = {
    DeadlineType.INTERNAL_START.value: 30,
    DeadlineType.VENDOR_OUTREACH.value: 28,
    DeadlineType.INFORMATION_DUE.value: 21,
    DeadlineType.DOCUMENT_PACKET_DUE.value: 16,
    DeadlineType.FORM_COMPLETION_DUE.value: 10,
    DeadlineType.SIGNATURE_DUE.value: 6,
    DeadlineType.SUBMISSION_DUE.value: 3,
}

#: Escalation ladder: days remaining -> who is told. Overdue escalations are
#: handled separately by app.deadlines.escalation.
DEFAULT_ESCALATION_LADDER: dict[int, str] = {
    120: EscalationLevel.OWNER.value,
    90: EscalationLevel.OWNER.value,
    60: EscalationLevel.OWNER.value,
    30: EscalationLevel.REVIEWER.value,
    14: EscalationLevel.REVIEWER.value,
    7: EscalationLevel.MANAGER.value,
    3: EscalationLevel.MANAGER.value,
    0: EscalationLevel.MANAGER.value,
}


class DeadlineRuleConfigError(ValueError):
    """A deadline rule's JSONB configuration is invalid."""


@dataclass(frozen=True, slots=True)
class DeadlinePolicy:
    """An evaluable deadline rule."""

    id: uuid.UUID | None
    rule_key: str
    obligation_type: str
    recurrence_type: str
    recurrence_config: dict[str, Any] = field(default_factory=dict)
    adjustment_policy: str = AdjustmentPolicy.NONE.value
    lead_time_days: int | None = None
    milestone_offsets: dict[str, int] = field(default_factory=dict)
    escalation_policy: dict[str, Any] = field(default_factory=dict)
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    priority: int = 100

    def is_effective_on(self, when: date) -> bool:
        if self.effective_from and when < self.effective_from:
            return False
        return not (self.effective_to and when > self.effective_to)

    @property
    def specificity(self) -> int:
        return (1 if self.jurisdiction_id else 0) + (1 if self.license_type_id else 0)

    def offsets(self, *, default_lead_days: int) -> dict[str, int]:
        """Resolve milestone offsets, scaled to the effective lead time.

        When a jurisdiction allows only a 10-day lead, a 30-day ladder would place
        every internal milestone in the past. Scaling keeps the sequence ordered
        and actionable instead of emitting a pile of instantly-overdue tasks.
        """
        if self.milestone_offsets:
            return {key: int(value) for key, value in self.milestone_offsets.items()}
        lead = self.lead_time_days if self.lead_time_days is not None else default_lead_days
        base_start = DEFAULT_MILESTONE_OFFSETS[DeadlineType.INTERNAL_START.value]
        if lead <= 0:
            return {}
        if lead == base_start:
            return dict(DEFAULT_MILESTONE_OFFSETS)
        scale = lead / base_start
        scaled: dict[str, int] = {}
        for key, offset in DEFAULT_MILESTONE_OFFSETS.items():
            value = round(offset * scale)
            # Never collapse a milestone onto the statutory date itself.
            scaled[key] = max(1, min(value, lead))
        scaled[DeadlineType.INTERNAL_START.value] = lead
        return scaled

    def escalation_ladder(self) -> dict[int, str]:
        configured = self.escalation_policy.get("ladder")
        if isinstance(configured, dict) and configured:
            try:
                return {int(days): str(level) for days, level in configured.items()}
            except (TypeError, ValueError) as exc:
                raise DeadlineRuleConfigError(
                    f"Escalation ladder keys must be integer day counts: {configured!r}"
                ) from exc
        return dict(DEFAULT_ESCALATION_LADDER)

    def alert_windows(self) -> tuple[int, ...]:
        configured = self.escalation_policy.get("alert_windows_days")
        if isinstance(configured, list) and configured:
            return tuple(sorted({int(value) for value in configured}, reverse=True))
        return DEFAULT_ALERT_WINDOWS


def validate_recurrence_config(recurrence_type: str, config: dict[str, Any]) -> None:
    """Fail fast on a recurrence configuration that cannot produce a date."""
    if recurrence_type not in {member.value for member in RecurrenceType}:
        raise DeadlineRuleConfigError(f"Unsupported recurrence type {recurrence_type!r}.")
    if recurrence_type == RecurrenceType.FIXED_ANNUAL_DATE.value:
        month, day = config.get("month"), config.get("day")
        if not isinstance(month, int) or not 1 <= month <= 12:
            raise DeadlineRuleConfigError("FIXED_ANNUAL_DATE requires 'month' between 1 and 12.")
        if not isinstance(day, int) or not 1 <= day <= 31:
            raise DeadlineRuleConfigError("FIXED_ANNUAL_DATE requires 'day' between 1 and 31.")
    if recurrence_type == RecurrenceType.CUSTOM_INTERVAL.value:
        months = int(config.get("interval_months", 0) or 0)
        days = int(config.get("interval_days", 0) or 0)
        if months <= 0 and days <= 0:
            raise DeadlineRuleConfigError(
                "CUSTOM_INTERVAL requires a positive 'interval_months' or 'interval_days'."
            )
    if recurrence_type == RecurrenceType.NMLS_ANNUAL_RENEWAL_WINDOW.value:
        month = config.get("window_end_month", 12)
        if not isinstance(month, int) or not 1 <= month <= 12:
            raise DeadlineRuleConfigError("NMLS window 'window_end_month' must be 1-12.")


def validate_milestone_offsets(offsets: dict[str, Any]) -> None:
    valid = {member.value for member in DeadlineType}
    for key, value in offsets.items():
        if key not in valid:
            raise DeadlineRuleConfigError(f"Unknown deadline type in milestone offsets: {key!r}.")
        if not isinstance(value, int) or value < 0:
            raise DeadlineRuleConfigError(
                f"Milestone offset for {key!r} must be a non-negative integer."
            )


def resolve_policy(
    policies: list[DeadlinePolicy],
    *,
    obligation_type: str,
    when: date,
    jurisdiction_id: uuid.UUID | None = None,
    license_type_id: uuid.UUID | None = None,
) -> DeadlinePolicy | None:
    """Pick the most specific in-force rule for an obligation."""
    candidates = [
        policy
        for policy in policies
        if policy.obligation_type == obligation_type
        and policy.is_effective_on(when)
        and (policy.jurisdiction_id is None or policy.jurisdiction_id == jurisdiction_id)
        and (policy.license_type_id is None or policy.license_type_id == license_type_id)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: (-p.specificity, p.priority, p.rule_key))[0]


__all__ = [
    "DEFAULT_ESCALATION_LADDER",
    "DEFAULT_MILESTONE_OFFSETS",
    "DeadlinePolicy",
    "DeadlineRuleConfigError",
    "resolve_policy",
    "validate_milestone_offsets",
    "validate_recurrence_config",
]
