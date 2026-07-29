"""Domain enumerations.

Stored in PostgreSQL as VARCHAR columns guarded by named CHECK constraints
(no native ENUM types in this milestone, so value changes stay cheap).
"""

from __future__ import annotations

from enum import StrEnum


class ProcessingState(StrEnum):
    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    ATTACHMENTS_SAVED = "ATTACHMENTS_SAVED"
    CLASSIFIED = "CLASSIFIED"
    TASK_CREATED = "TASK_CREATED"
    MOVED = "MOVED"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_REVIEW = "FAILED_REVIEW"


class RecipientType(StrEnum):
    TO = "TO"
    CC = "CC"
    BCC = "BCC"
    REPLY_TO = "REPLY_TO"


class AttachmentStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    DOWNLOADED = "DOWNLOADED"
    REFERENCE_NOT_DOWNLOADED = "REFERENCE_NOT_DOWNLOADED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class EmailType(StrEnum):
    MISSING_INFORMATION_REQUEST = "missing_information_request"
    RENEWAL_NOTICE = "renewal_notice"
    BOND_CORRESPONDENCE = "bond_correspondence"
    ANNUAL_REPORT_OR_ASSESSMENT = "annual_report_or_assessment"
    INVOICE_OR_FEE = "invoice_or_fee"
    SUBMISSION_CONFIRMATION = "submission_confirmation"
    LICENSE_OR_PROOF_RECEIVED = "license_or_proof_received"
    REGULATOR_CORRESPONDENCE = "regulator_correspondence"
    INTERNAL_FOLLOWUP = "internal_followup"
    GENERAL_CORRESPONDENCE = "general_correspondence"


class ReviewDecision(StrEnum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    RECLASSIFICATION_REQUESTED = "RECLASSIFICATION_REQUESTED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    WAITING_FOR_INFO = "WAITING_FOR_INFO"
    READY_TO_SEND = "READY_TO_SEND"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    OVERDUE = "OVERDUE"


class DraftStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CREATED = "CREATED"
    SENT = "SENT"
    FAILED = "FAILED"


class RequestedItemStatus(StrEnum):
    OPEN = "OPEN"
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    IMPORT = "IMPORT"


class GraphSubscriptionStatus(StrEnum):
    CREATING = "CREATING"
    ACTIVE = "ACTIVE"
    RENEWAL_REQUIRED = "RENEWAL_REQUIRED"
    REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED"
    REMOVED = "REMOVED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


# Statuses that occupy the single active-subscription slot per folder.
ACTIVE_SUBSCRIPTION_STATUSES = (
    GraphSubscriptionStatus.CREATING,
    GraphSubscriptionStatus.ACTIVE,
    GraphSubscriptionStatus.RENEWAL_REQUIRED,
    GraphSubscriptionStatus.REAUTHORIZATION_REQUIRED,
)


class NotificationReceiptStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    INVALID_CLIENT_STATE = "INVALID_CLIENT_STATE"
    UNKNOWN_SUBSCRIPTION = "UNKNOWN_SUBSCRIPTION"
    MALFORMED = "MALFORMED"


class FolderMembership(StrEnum):
    PRESENT = "PRESENT"
    REMOVED = "REMOVED"
    UNKNOWN = "UNKNOWN"
