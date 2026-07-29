"""Form-preparation enumerations."""

from __future__ import annotations

from enum import StrEnum


class FormFamily(StrEnum):
    """Structural family of a template.

    NMLS families model *our own* governed worksheet data so an authorized user
    can transcribe it during a filing. Milestone 6 does not reproduce or submit
    proprietary NMLS screens.
    """

    NMLS_MU1 = "NMLS_MU1"
    NMLS_MU2 = "NMLS_MU2"
    NMLS_MU3 = "NMLS_MU3"
    STATE_APPLICATION = "STATE_APPLICATION"
    STATE_RENEWAL = "STATE_RENEWAL"
    BOND_FORM = "BOND_FORM"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    VENDOR_FORM = "VENDOR_FORM"
    INTERNAL_WORKSHEET = "INTERNAL_WORKSHEET"
    OTHER = "OTHER"


NMLS_FORM_FAMILIES: tuple[str, ...] = (
    FormFamily.NMLS_MU1.value,
    FormFamily.NMLS_MU2.value,
    FormFamily.NMLS_MU3.value,
)


class FormFormat(StrEnum):
    PDF_ACROFORM = "PDF_ACROFORM"
    FLAT_PDF = "FLAT_PDF"
    DOCX = "DOCX"
    XLSX = "XLSX"
    WEB_WORKSHEET = "WEB_WORKSHEET"
    UNKNOWN = "UNKNOWN"


#: Formats we can mechanically fill. Everything else produces a worksheet.
FILLABLE_FORMATS: frozenset[str] = frozenset({FormFormat.PDF_ACROFORM.value, FormFormat.DOCX.value})

#: Formats that must never be positionally guessed in production.
WORKSHEET_ONLY_FORMATS: frozenset[str] = frozenset(
    {
        FormFormat.FLAT_PDF.value,
        FormFormat.WEB_WORKSHEET.value,
        FormFormat.XLSX.value,
        FormFormat.UNKNOWN.value,
    }
)


class FieldDetectionStatus(StrEnum):
    NOT_INSPECTED = "NOT_INSPECTED"
    INSPECTED = "INSPECTED"
    NO_FIELDS_FOUND = "NO_FIELDS_FOUND"
    MANUAL_MAPPING_REQUIRED = "MANUAL_MAPPING_REQUIRED"
    INSPECTION_FAILED = "INSPECTION_FAILED"


class FormTemplateStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FormFieldType(StrEnum):
    TEXT = "TEXT"
    MULTILINE_TEXT = "MULTILINE_TEXT"
    NUMBER = "NUMBER"
    CURRENCY = "CURRENCY"
    DATE = "DATE"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    CHOICE = "CHOICE"
    SIGNATURE = "SIGNATURE"
    INITIALS = "INITIALS"
    ATTESTATION = "ATTESTATION"
    COMPUTED = "COMPUTED"
    UNKNOWN = "UNKNOWN"


#: Field types a human must personally execute. The system records the
#: requirement and never fabricates the mark.
HUMAN_EXECUTION_FIELD_TYPES: frozenset[str] = frozenset(
    {
        FormFieldType.SIGNATURE.value,
        FormFieldType.INITIALS.value,
        FormFieldType.ATTESTATION.value,
    }
)


class FieldSourceType(StrEnum):
    INFORMATION_REGISTRY = "INFORMATION_REGISTRY"
    LEGAL_ENTITY = "LEGAL_ENTITY"
    LICENSE_INVENTORY = "LICENSE_INVENTORY"
    COMPLIANCE_CASE = "COMPLIANCE_CASE"
    DOCUMENT_METADATA = "DOCUMENT_METADATA"
    MANUAL_INPUT = "MANUAL_INPUT"
    SIGNATURE_REQUIRED = "SIGNATURE_REQUIRED"
    CALCULATED = "CALCULATED"


class MappingStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class FormInstanceStatus(StrEnum):
    DRAFT = "DRAFT"
    PREFILLED = "PREFILLED"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED_FOR_SIGNATURE = "APPROVED_FOR_SIGNATURE"
    SIGNATURE_PENDING = "SIGNATURE_PENDING"
    SIGNED = "SIGNED"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    SUBMITTED_EXTERNALLY = "SUBMITTED_EXTERNALLY"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


#: Once a form instance reaches these states its field values are frozen.
FROZEN_INSTANCE_STATUSES: tuple[str, ...] = (
    FormInstanceStatus.APPROVED_FOR_SIGNATURE.value,
    FormInstanceStatus.SIGNATURE_PENDING.value,
    FormInstanceStatus.SIGNED.value,
    FormInstanceStatus.READY_FOR_SUBMISSION.value,
    FormInstanceStatus.SUBMITTED_EXTERNALLY.value,
    FormInstanceStatus.SUPERSEDED.value,
)


class FormFieldValueStatus(StrEnum):
    AUTO_FILLED = "AUTO_FILLED"
    MANUALLY_FILLED = "MANUALLY_FILLED"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    SIGNATURE_REQUIRED = "SIGNATURE_REQUIRED"
    MANUAL_ONLY = "MANUAL_ONLY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Statuses that block "ready for review" because information is outstanding.
OUTSTANDING_FIELD_STATUSES: tuple[str, ...] = (
    FormFieldValueStatus.NEEDS_INFORMATION.value,
    FormFieldValueStatus.NEEDS_REVIEW.value,
)

#: Statuses considered resolved for review purposes. SIGNATURE_REQUIRED counts as
#: resolved: the requirement is recorded and executed by a human downstream.
RESOLVED_FIELD_STATUSES: tuple[str, ...] = (
    FormFieldValueStatus.APPROVED.value,
    FormFieldValueStatus.SIGNATURE_REQUIRED.value,
    FormFieldValueStatus.NOT_APPLICABLE.value,
)


class FormValidationCode(StrEnum):
    REQUIRED_FIELD_EMPTY = "REQUIRED_FIELD_EMPTY"
    VALUE_NOT_IN_ALLOWED_SET = "VALUE_NOT_IN_ALLOWED_SET"
    STALE_INFORMATION_VALUE = "STALE_INFORMATION_VALUE"
    EXPIRED_INFORMATION_VALUE = "EXPIRED_INFORMATION_VALUE"
    UNAPPROVED_INFORMATION_VALUE = "UNAPPROVED_INFORMATION_VALUE"
    WRONG_ENTITY_INFORMATION_VALUE = "WRONG_ENTITY_INFORMATION_VALUE"
    MAPPING_NOT_APPROVED = "MAPPING_NOT_APPROVED"
    SIGNATURE_FIELD_OUTSTANDING = "SIGNATURE_FIELD_OUTSTANDING"
    UNMAPPED_FIELD = "UNMAPPED_FIELD"
    TEMPLATE_FIELD_MISMATCH = "TEMPLATE_FIELD_MISMATCH"
    FORMAT_NOT_FILLABLE = "FORMAT_NOT_FILLABLE"
    SIGNED_HASH_MISMATCH = "SIGNED_HASH_MISMATCH"


class SignatureRequirementStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    IDENTIFIED = "IDENTIFIED"
    APPROVED_FOR_SIGNATURE = "APPROVED_FOR_SIGNATURE"
    SENT_FOR_SIGNATURE_EXTERNALLY = "SENT_FOR_SIGNATURE_EXTERNALLY"
    SIGNED_EVIDENCE_RECORDED = "SIGNED_EVIDENCE_RECORDED"
    CANCELLED = "CANCELLED"
