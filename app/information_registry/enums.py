"""Reusable-information registry enumerations."""

from __future__ import annotations

from enum import StrEnum


class InformationCategory(StrEnum):
    CONTACT_INFORMATION = "CONTACT_INFORMATION"
    CORPORATE_INFORMATION = "CORPORATE_INFORMATION"
    OFFICER_INFORMATION = "OFFICER_INFORMATION"
    OWNERSHIP_INFORMATION = "OWNERSHIP_INFORMATION"
    POLICY_INFORMATION = "POLICY_INFORMATION"
    FINANCIAL_INFORMATION = "FINANCIAL_INFORMATION"
    LICENSING_INFORMATION = "LICENSING_INFORMATION"
    BOND_INFORMATION = "BOND_INFORMATION"
    OPERATIONAL_INFORMATION = "OPERATIONAL_INFORMATION"
    ATTESTATION = "ATTESTATION"
    SIGNATURE_INFORMATION = "SIGNATURE_INFORMATION"


class InformationDataType(StrEnum):
    TEXT = "TEXT"
    LONG_TEXT = "LONG_TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    URL = "URL"
    ADDRESS = "ADDRESS"
    CURRENCY = "CURRENCY"
    ENUM = "ENUM"
    JSON = "JSON"
    DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"


class Sensitivity(StrEnum):
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    HIGHLY_RESTRICTED = "HIGHLY_RESTRICTED"


#: Values at or above this level are always stored encrypted, always masked in
#: list responses, and never exposed to an AI provider.
ENCRYPTED_SENSITIVITIES: frozenset[str] = frozenset(
    {Sensitivity.RESTRICTED.value, Sensitivity.HIGHLY_RESTRICTED.value}
)

#: Levels forbidden from any AI prompt or external model call.
AI_FORBIDDEN_SENSITIVITIES: frozenset[str] = frozenset(
    {
        Sensitivity.CONFIDENTIAL.value,
        Sensitivity.RESTRICTED.value,
        Sensitivity.HIGHLY_RESTRICTED.value,
    }
)


class ReusablePolicy(StrEnum):
    """How broadly an approved value may be reused.

    ``ENTITY_ONLY`` is the default. Cross-entity reuse is never implicit: it
    requires ``ALL_ENTITIES_APPROVED`` plus a manager approval record.
    """

    ENTITY_ONLY = "ENTITY_ONLY"
    ENTITY_AND_JURISDICTION = "ENTITY_AND_JURISDICTION"
    LICENSE_SPECIFIC = "LICENSE_SPECIFIC"
    VENDOR_SPECIFIC = "VENDOR_SPECIFIC"
    CASE_SPECIFIC = "CASE_SPECIFIC"
    ALL_ENTITIES_APPROVED = "ALL_ENTITIES_APPROVED"
    NOT_REUSABLE = "NOT_REUSABLE"


class InformationValueStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


#: Only an APPROVED, in-date value may autofill a form or enter a packet.
USABLE_VALUE_STATUSES: tuple[str, ...] = (InformationValueStatus.APPROVED.value,)


class ValueFreshness(StrEnum):
    FRESH = "FRESH"
    DUE_FOR_REVIEW = "DUE_FOR_REVIEW"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    NOT_TRACKED = "NOT_TRACKED"


class UsagePurpose(StrEnum):
    FORM_PREFILL = "FORM_PREFILL"
    PACKET_ASSEMBLY = "PACKET_ASSEMBLY"
    VENDOR_ANSWER = "VENDOR_ANSWER"
    CASE_REFERENCE = "CASE_REFERENCE"
    WORKSHEET_EXPORT = "WORKSHEET_EXPORT"
    MANUAL_LOOKUP = "MANUAL_LOOKUP"
