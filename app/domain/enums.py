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
    GENERAL_CORRESPONDENCE = "general_correspondence"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    WAITING_FOR_INFO = "WAITING_FOR_INFO"
    READY_TO_SEND = "READY_TO_SEND"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


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
