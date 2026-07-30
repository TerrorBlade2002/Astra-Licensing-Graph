"""Request and response contracts for supervised portal assistance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PortalCreate(BaseModel):
    portal_key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=300)
    portal_type: str
    base_url: str
    owner_organization_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None
    supported_filing_types: list[str] = Field(default_factory=list)
    approved_automation_level: str = "PREPARE_ONLY"
    data_classification: str = "CONFIDENTIAL"
    credential_model: str = "UNKNOWN"
    mfa_model: str | None = None
    captcha_expected: bool = False
    terms_review_required: bool = True


class PortalUpdate(BaseModel):
    name: str | None = None
    supported_filing_types: list[str] | None = None
    approved_automation_level: str | None = None
    status: str | None = None
    mfa_model: str | None = None
    captcha_expected: bool | None = None
    terms_review_required: bool | None = None
    terms_review_expires_at: datetime | None = None


class PortalOut(ORMModel):
    id: uuid.UUID
    portal_key: str
    name: str
    portal_type: str
    base_url: str
    hostname: str
    jurisdiction_id: uuid.UUID | None
    supported_filing_types: list[str]
    approved_automation_level: str
    status: str
    data_classification: str
    credential_model: str
    mfa_model: str | None
    captcha_expected: bool
    terms_review_required: bool
    terms_review_expires_at: datetime | None
    final_submit_human_only: bool
    payment_human_only: bool
    attestation_human_only: bool
    signature_human_only: bool
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewCreate(BaseModel):
    terms_reference: str | None = None
    terms_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    terms_effective_date: date | None = None
    allowed_actions: dict[str, bool] = Field(default_factory=dict)
    prohibited_actions: dict[str, bool] = Field(default_factory=dict)
    approved_filing_types: list[str] = Field(default_factory=list)
    approved_entity_ids: list[uuid.UUID] = Field(default_factory=list)
    security_findings: list[dict[str, Any]] = Field(default_factory=list)
    review_notes: str | None = Field(default=None, max_length=4000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class ReviewOut(ORMModel):
    id: uuid.UUID
    portal_definition_id: uuid.UUID
    version: int
    status: str
    terms_reference: str | None
    terms_sha256: str | None
    terms_effective_date: date | None
    allowed_actions: dict[str, Any]
    prohibited_actions: dict[str, Any]
    approved_filing_types: list[str]
    approved_entity_ids: list[uuid.UUID]
    security_findings: list[dict[str, Any]]
    review_notes: str | None
    reviewed_by_compliance: str | None
    reviewed_by_security: str | None
    approved_by_actor: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    created_at: datetime


class AuthorizationUpsert(BaseModel):
    user_principal_id: uuid.UUID
    external_account_reference: str | None = Field(default=None, max_length=300)
    portal_role: str | None = Field(default=None, max_length=120)
    authorization_status: str = "ACTIVE"
    authorized_filing_types: list[str] = Field(default_factory=list)
    authorized_entity_ids: list[uuid.UUID] = Field(default_factory=list)
    expires_at: datetime | None = None


class AuthorizationOut(ORMModel):
    id: uuid.UUID
    portal_definition_id: uuid.UUID
    user_principal_id: uuid.UUID
    external_account_reference: str | None
    portal_role: str | None
    authorization_status: str
    authorized_filing_types: list[str]
    authorized_entity_ids: list[uuid.UUID]
    authorized_at: datetime | None
    expires_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdapterCreate(BaseModel):
    adapter_key: str = Field(min_length=2, max_length=120)
    supported_routes: dict[str, Any] = Field(default_factory=dict)
    locator_contract: dict[str, Any]
    field_mapping_version: str | None = None
    test_fixture_version: str | None = None
    source_revision: str | None = None


class AdapterOut(ORMModel):
    id: uuid.UUID
    portal_definition_id: uuid.UUID
    adapter_key: str
    version: int
    status: str
    supported_routes: dict[str, Any]
    locator_contract: dict[str, Any]
    field_mapping_version: str | None
    test_fixture_version: str | None
    source_revision: str | None
    approved_by_actor: str | None
    activated_at: datetime | None
    created_at: datetime


class FieldMappingCreate(BaseModel):
    filing_type: str
    portal_field_key: str
    portal_label: str | None = None
    locator_strategy: dict[str, Any]
    source_type: str
    source_key: str | None = None
    transformation_key: str | None = None
    required: bool = False
    sensitivity: str = "INTERNAL"
    human_only: bool = False
    requires_fresh_confirmation: bool = False
    allowed_values: dict[str, Any] | list[Any] | None = None
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 100


class RunCreate(BaseModel):
    portal_definition_id: uuid.UUID
    filing_type: str
    automation_level: str | None = None
    assigned_operator_id: uuid.UUID | None = None
    assigned_signatory_id: uuid.UUID | None = None
    assigned_payment_approver_id: uuid.UUID | None = None
    license_id: uuid.UUID | None = None
    form_instance_id: uuid.UUID | None = None
    document_packet_id: uuid.UUID | None = None
    earliest_start_at: datetime | None = None
    deadline_at: datetime | None = None


class RunUpdate(BaseModel):
    assigned_operator_id: uuid.UUID | None = None
    assigned_signatory_id: uuid.UUID | None = None
    assigned_payment_approver_id: uuid.UUID | None = None
    deadline_at: datetime | None = None


class PortalNavigationRequest(BaseModel):
    route_key: str = Field(min_length=1, max_length=120)
    request_id: uuid.UUID


class RunOut(ORMModel):
    id: uuid.UUID
    run_key: str
    portal_definition_id: uuid.UUID
    portal_review_version_id: uuid.UUID
    portal_adapter_version_id: uuid.UUID | None
    compliance_case_id: uuid.UUID
    legal_entity_id: uuid.UUID
    license_id: uuid.UUID | None
    form_instance_id: uuid.UUID | None
    document_packet_id: uuid.UUID | None
    filing_type: str
    automation_level: str
    status: str
    current_stage: str
    assigned_operator_id: uuid.UUID | None
    assigned_signatory_id: uuid.UUID | None
    assigned_payment_approver_id: uuid.UUID | None
    earliest_start_at: datetime | None
    deadline_at: datetime | None
    started_at: datetime | None
    submitted_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


class BrowserSessionOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    operator_user_id: uuid.UUID
    worker_id: str
    session_status: str
    browser_type: str
    ephemeral_profile_id: str
    started_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    created_at: datetime


class HandoffCreate(BaseModel):
    handoff_type: str
    requested_from_user_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class HandoffComplete(BaseModel):
    result: str = Field(min_length=1, max_length=120)
    operator_confirmation: str | None = Field(default=None, max_length=1000)
    evidence_reference: str | None = Field(default=None, max_length=1000)
    observed_page_category: str | None = Field(default=None, max_length=120)


class HandoffOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    browser_session_id: uuid.UUID | None
    handoff_type: str
    status: str
    requested_from_user_id: uuid.UUID | None
    requested_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    result: str | None
    operator_confirmation: str | None
    evidence_reference: str | None
    expires_at: datetime | None
    created_at: datetime


class RunFieldOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    portal_field_key: str
    label: str | None
    approved_source_type: str | None
    approved_source_record_id: uuid.UUID | None
    displayed_value_redacted: str | None
    status: str
    entered_by: str | None
    entered_at: datetime | None
    verified_by: str | None
    verified_at: datetime | None
    discrepancy_code: str | None
    discrepancy_details: dict[str, Any] | None


class FieldObservation(BaseModel):
    displayed_value: str = Field(max_length=2000)
    expected_approved_fingerprint: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    sensitive: bool = False


class RunDocumentOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    expected_filename: str
    expected_sha256: str
    portal_document_category: str | None
    status: str
    portal_upload_reference: str | None
    portal_display_name: str | None
    portal_size_bytes: int | None
    uploaded_by: str | None
    uploaded_at: datetime | None
    verified_at: datetime | None
    discrepancy_details: dict[str, Any] | None


class DocumentObservation(BaseModel):
    portal_display_name: str = Field(max_length=500)
    portal_size_bytes: int = Field(ge=0)
    portal_upload_reference: str | None = Field(default=None, max_length=500)


class ValidationCapture(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    observed_page_category: str = Field(max_length=120)


class SnapshotOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    version: int
    form_instance_version: int | None
    field_manifest: list[dict[str, Any]]
    document_manifest: list[dict[str, Any]]
    portal_validation_messages: list[dict[str, Any]]
    discrepancy_report: list[dict[str, Any]]
    screenshot_manifest: list[dict[str, Any]]
    snapshot_sha256: str
    status: str
    created_by_actor: str | None
    reviewed_by_actor: str | None
    reviewed_at: datetime | None
    created_at: datetime


class SnapshotDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AttestationOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    attestation_type: str
    required_actor_id: uuid.UUID | None
    status: str
    attestation_text_fingerprint: str | None
    displayed_text_reference: str | None
    completed_by_actor: str | None
    completed_at: datetime | None
    evidence_reference: str | None
    created_at: datetime


class HumanCompletion(BaseModel):
    resulting_page_category: str = Field(min_length=1, max_length=120)
    evidence_reference: str | None = Field(default=None, max_length=1000)


class SignatureCompletion(BaseModel):
    evidence_reference: str | None = Field(default=None, max_length=1000)


class PaymentOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    status: str
    expected_fee_amount: Decimal | None
    currency: str | None
    portal_fee_summary: dict[str, Any] | None
    approved_by_actor: str | None
    approved_at: datetime | None
    paid_by_actor: str | None
    paid_at: datetime | None
    payment_reference_redacted: str | None
    receipt_document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ExternalPayment(BaseModel):
    payment_reference_redacted: str | None = Field(default=None, max_length=120)
    receipt_document_id: uuid.UUID | None = None

    @field_validator("payment_reference_redacted")
    @classmethod
    def require_redaction(cls, value: str | None) -> str | None:
        if value and len("".join(char for char in value if char.isdigit())) > 4:
            raise ValueError("Payment reference must expose no more than four digits.")
        return value


class SubmissionEvidenceCreate(BaseModel):
    evidence_type: str
    confirmation_number: str | None = Field(default=None, max_length=300)
    filing_reference: str | None = Field(default=None, max_length=300)
    submission_status: str | None = Field(default=None, max_length=120)
    submitted_at: datetime | None = None
    source_document_id: uuid.UUID | None = None
    screenshot_storage_uri: str | None = Field(default=None, max_length=1000)
    receipt_storage_uri: str | None = Field(default=None, max_length=1000)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    notes: str | None = Field(default=None, max_length=2000)


class SubmissionEvidenceOut(ORMModel):
    id: uuid.UUID
    portal_run_id: uuid.UUID
    evidence_type: str
    confirmation_number: str | None
    filing_reference: str | None
    submission_status: str | None
    submitted_by_actor: str | None
    submitted_at: datetime | None
    source_document_id: uuid.UUID | None
    screenshot_storage_uri: str | None
    receipt_storage_uri: str | None
    evidence_sha256: str | None
    evidence_verified_by_actor: str | None
    verified_at: datetime | None
    notes: str | None
    created_at: datetime


class CaptureSubmissionResult(BaseModel):
    outcome: str
    resulting_page_category: str
    ambiguous: bool = False
    confirmation_number: str | None = Field(default=None, max_length=300)
    filing_reference: str | None = Field(default=None, max_length=300)
    evidence_document_id: uuid.UUID | None = None
