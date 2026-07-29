"""Strict versioned classification contract shared by rules, AI, API, and portal."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EmailType = Literal[
    "missing_information_request",
    "renewal_notice",
    "bond_correspondence",
    "annual_report_or_assessment",
    "invoice_or_fee",
    "submission_confirmation",
    "license_or_proof_received",
    "regulator_correspondence",
    "internal_followup",
    "general_correspondence",
]
RequestCategory = Literal[
    "contact_information",
    "officer_information",
    "ownership_information",
    "corporate_information",
    "policy_information",
    "financial_information",
    "licensing_information",
    "bond_information",
    "payment_information",
    "supporting_document",
    "attestation",
    "signature",
    "unknown",
]


class RequestedInformationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(min_length=2, max_length=500)
    category: RequestCategory
    required: bool
    evidence_quote: str = Field(min_length=2, max_length=1000)


class ClassificationDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str
    document_type: str
    relationship: str


class ClassificationOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str | None
    email_type: EmailType
    states: list[str]
    license_types: list[str]
    license_numbers: list[str]
    action_required: bool
    requested_information: list[RequestedInformationV1]
    documents: list[ClassificationDocumentV1]
    due_date: date | None
    summary: str = Field(max_length=1000)
    proposed_action: str = Field(max_length=1000)
    suggested_destination: str
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool
    review_reasons: list[str]

    @field_validator("states")
    @classmethod
    def unique_states(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


def strict_json_schema() -> dict[str, object]:
    """JSON Schema passed to Structured Outputs with additional properties forbidden."""
    return ClassificationOutputV1.model_json_schema()
