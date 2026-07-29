"""Deadline-engine enumerations."""

from __future__ import annotations

from enum import StrEnum


class RecurrenceType(StrEnum):
    FIXED_ANNUAL_DATE = "FIXED_ANNUAL_DATE"
    ISSUE_ANNIVERSARY = "ISSUE_ANNIVERSARY"
    EXPIRATION_ANNIVERSARY = "EXPIRATION_ANNIVERSARY"
    REGULATOR_SUPPLIED = "REGULATOR_SUPPLIED"
    NMLS_ANNUAL_RENEWAL_WINDOW = "NMLS_ANNUAL_RENEWAL_WINDOW"
    BOND_EXPIRATION = "BOND_EXPIRATION"
    ANNUAL_REPORT_DATE = "ANNUAL_REPORT_DATE"
    RELATIVE_TO_CASE_EVENT = "RELATIVE_TO_CASE_EVENT"
    CUSTOM_INTERVAL = "CUSTOM_INTERVAL"
    MANUAL_DATE = "MANUAL_DATE"


class AdjustmentPolicy(StrEnum):
    """Whether a due date moves when it lands on a non-business day.

    ``NONE`` is the default on purpose: assuming every regulator grants a
    next-business-day grace period is how real filings get missed.
    """

    NONE = "NONE"
    PREVIOUS_BUSINESS_DAY = "PREVIOUS_BUSINESS_DAY"
    NEXT_BUSINESS_DAY = "NEXT_BUSINESS_DAY"
    JURISDICTION_SPECIFIC = "JURISDICTION_SPECIFIC"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DeadlineRuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DeadlineType(StrEnum):
    INTERNAL_START = "INTERNAL_START"
    VENDOR_OUTREACH = "VENDOR_OUTREACH"
    INFORMATION_DUE = "INFORMATION_DUE"
    DOCUMENT_PACKET_DUE = "DOCUMENT_PACKET_DUE"
    FORM_COMPLETION_DUE = "FORM_COMPLETION_DUE"
    SIGNATURE_DUE = "SIGNATURE_DUE"
    SUBMISSION_DUE = "SUBMISSION_DUE"
    STATUTORY_DUE = "STATUTORY_DUE"
    BOND_EXPIRY = "BOND_EXPIRY"
    ANNUAL_REPORT_DUE = "ANNUAL_REPORT_DUE"
    DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY"
    FOLLOW_UP = "FOLLOW_UP"


#: Internal milestones the engine derives from a statutory anchor. These may be
#: shifted for convenience; the statutory date may not.
INTERNAL_DEADLINE_TYPES: tuple[str, ...] = (
    DeadlineType.INTERNAL_START.value,
    DeadlineType.VENDOR_OUTREACH.value,
    DeadlineType.INFORMATION_DUE.value,
    DeadlineType.DOCUMENT_PACKET_DUE.value,
    DeadlineType.FORM_COMPLETION_DUE.value,
    DeadlineType.SIGNATURE_DUE.value,
    DeadlineType.SUBMISSION_DUE.value,
    DeadlineType.FOLLOW_UP.value,
)


class DeadlineStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    APPROACHING = "APPROACHING"
    DUE_TODAY = "DUE_TODAY"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


OPEN_DEADLINE_STATUSES: tuple[str, ...] = (
    DeadlineStatus.SCHEDULED.value,
    DeadlineStatus.APPROACHING.value,
    DeadlineStatus.DUE_TODAY.value,
    DeadlineStatus.OVERDUE.value,
)


class DeadlineSeverity(StrEnum):
    INFORMATIONAL = "INFORMATIONAL"
    NORMAL = "NORMAL"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"
    REGULATORY_RISK = "REGULATORY_RISK"


class DeadlineEventType(StrEnum):
    CREATED = "CREATED"
    RECALCULATED = "RECALCULATED"
    MANUALLY_OVERRIDDEN = "MANUALLY_OVERRIDDEN"
    OWNER_CHANGED = "OWNER_CHANGED"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class EscalationLevel(StrEnum):
    OWNER = "OWNER"
    BACKUP_OWNER = "BACKUP_OWNER"
    REVIEWER = "REVIEWER"
    MANAGER = "MANAGER"
    COUNSEL = "COUNSEL"
    EXECUTIVE = "EXECUTIVE"


#: Default alert ladder in days before the due date. ``0`` means due today and
#: negative values represent overdue escalations.
DEFAULT_ALERT_WINDOWS: tuple[int, ...] = (120, 90, 60, 30, 14, 7, 3, 0)
