"""Pydantic v2 request and response models for the licensing API.

Response models never expose a decrypted sensitive value. Registry and form field
payloads carry ``display_value``/``display_value_redacted`` only; revealing a
restricted value is a separate, audited endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------- shared


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------- legal entities


class LegalEntityCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    entity_type: str
    entity_key: str | None = Field(default=None, max_length=80)
    display_name: str | None = None
    formation_jurisdiction: str | None = None
    formation_date: date | None = None
    #: A vault/registry pointer, never a raw tax identifier.
    tax_identifier_reference: str | None = None
    nmls_id: str | None = None
    primary_business_address: dict[str, Any] | None = None
    mailing_address: dict[str, Any] | None = None
    status: str | None = None
    is_in_scope: bool = True
    out_of_scope_reason: str | None = None


class LegalEntityUpdate(BaseModel):
    legal_name: str | None = None
    display_name: str | None = None
    entity_type: str | None = None
    status: str | None = None
    nmls_id: str | None = None
    primary_business_address: dict[str, Any] | None = None
    mailing_address: dict[str, Any] | None = None
    is_in_scope: bool | None = None
    out_of_scope_reason: str | None = None


class LegalEntityOut(ORMModel):
    id: uuid.UUID
    entity_key: str
    legal_name: str
    display_name: str | None
    entity_type: str
    formation_jurisdiction: str | None
    formation_date: date | None
    nmls_id: str | None
    status: str
    is_in_scope: bool
    out_of_scope_reason: str | None
    created_at: datetime
    updated_at: datetime


class OperatingProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    facts: dict[str, Any] = Field(default_factory=dict)
    effective_from: date | None = None


class OperatingProfileOut(ORMModel):
    id: uuid.UUID
    legal_entity_id: uuid.UUID
    name: str
    version: int
    status: str
    effective_from: date | None
    effective_to: date | None
    facts: dict[str, Any]
    approved_by_actor: str | None
    approved_at: datetime | None
    created_at: datetime


# ------------------------------------------------------------------- inventory


class LicenseCreate(BaseModel):
    legal_entity_id: uuid.UUID
    jurisdiction_id: uuid.UUID
    license_type_id: uuid.UUID
    license_number: str | None = None
    nmls_license_id: str | None = None
    filing_channel: str | None = None
    current_status: str | None = None
    #: Set when the entity genuinely holds more than one authority of this type.
    represents_additional_authority: bool = False
    authority_label: str | None = None
    regulator_organization_id: uuid.UUID | None = None
    vendor_organization_id: uuid.UUID | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_due_date: date | None = None
    responsible_owner: str | None = None
    source_document_id: uuid.UUID | None = None
    notes: str | None = None
    source_confidence: str | None = None


class LicenseUpdate(BaseModel):
    license_number: str | None = None
    nmls_license_id: str | None = None
    filing_channel: str | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_due_date: date | None = None
    internal_start_date: date | None = None
    next_review_date: date | None = None
    responsible_owner: str | None = None
    vendor_organization_id: uuid.UUID | None = None
    regulator_organization_id: uuid.UUID | None = None
    notes: str | None = None
    source_confidence: str | None = None
    authority_label: str | None = None


class LicenseTransition(BaseModel):
    to_status: str
    note: str | None = None
    source_type: str | None = None
    source_reference: str | None = None
    effective_at: datetime | None = None


class LicenseRenewedEvidence(BaseModel):
    new_expiration_date: date
    new_issue_date: date | None = None
    license_number: str | None = None
    evidence_document_id: uuid.UUID | None = None


class LicenseOut(ORMModel):
    id: uuid.UUID
    license_key: str
    legal_entity_id: uuid.UUID
    jurisdiction_id: uuid.UUID
    license_type_id: uuid.UUID
    license_number: str | None
    nmls_license_id: str | None
    filing_channel: str
    current_status: str
    represents_additional_authority: bool
    authority_label: str | None
    issue_date: date | None
    effective_date: date | None
    expiration_date: date | None
    renewal_due_date: date | None
    internal_start_date: date | None
    surrender_date: date | None
    next_review_date: date | None
    responsible_owner: str | None
    source_document_id: uuid.UUID | None
    source_confidence: str
    last_verified_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LicenseStatusEventOut(ORMModel):
    id: uuid.UUID
    license_id: uuid.UUID
    from_status: str | None
    to_status: str
    effective_at: datetime
    actor_id: str | None
    source_type: str | None
    source_reference: str | None
    note: str | None
    occurred_at: datetime


class LicenseListOut(BaseModel):
    items: list[LicenseOut]
    meta: PageMeta


class BondCreate(BaseModel):
    legal_entity_id: uuid.UUID
    license_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None
    bond_provider_organization_id: uuid.UUID | None = None
    bond_number: str | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    status: str = "PENDING"
    bond_channel: str = "UNKNOWN"
    effective_date: date | None = None
    expiration_date: date | None = None
    continuous: bool = False
    cancellation_notice_date: date | None = None
    bond_form_document_id: uuid.UUID | None = None
    rider_document_id: uuid.UUID | None = None
    continuation_document_id: uuid.UUID | None = None
    responsible_owner: str | None = None
    notes: str | None = None


class BondUpdate(BaseModel):
    bond_number: str | None = None
    amount: float | None = Field(default=None, ge=0)
    status: str | None = None
    bond_channel: str | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    continuous: bool | None = None
    cancellation_notice_date: date | None = None
    bond_form_document_id: uuid.UUID | None = None
    rider_document_id: uuid.UUID | None = None
    continuation_document_id: uuid.UUID | None = None
    responsible_owner: str | None = None
    notes: str | None = None


class BondOut(ORMModel):
    id: uuid.UUID
    bond_key: str
    legal_entity_id: uuid.UUID
    license_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID | None
    bond_provider_organization_id: uuid.UUID | None
    bond_number: str | None
    amount: float | None
    currency: str
    status: str
    bond_channel: str
    effective_date: date | None
    expiration_date: date | None
    continuous: bool
    cancellation_notice_date: date | None
    bond_form_document_id: uuid.UUID | None
    rider_document_id: uuid.UUID | None
    continuation_document_id: uuid.UUID | None
    responsible_owner: str | None
    notes: str | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- requirements


class AssessmentCreate(BaseModel):
    legal_entity_id: uuid.UUID
    operating_profile_id: uuid.UUID
    requested_jurisdictions: list[uuid.UUID] = Field(min_length=1)
    assessment_type: str | None = None
    #: What-if overrides layered over the profile's recorded facts.
    extra_facts: dict[str, Any] | None = None
    effective_date: date | None = None
    rule_set_name: str | None = None


class AssessmentOut(ORMModel):
    id: uuid.UUID
    assessment_key: str
    legal_entity_id: uuid.UUID
    operating_profile_id: uuid.UUID
    assessment_type: str
    status: str
    requested_jurisdictions: list[uuid.UUID]
    input_fingerprint: str
    rule_set_id: uuid.UUID
    effective_date: date | None
    created_by_actor: str
    reviewed_by_actor: str | None
    reviewed_at: datetime | None
    evaluated_at: datetime | None
    created_at: datetime


class AssessmentResultOut(ORMModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    jurisdiction_id: uuid.UUID
    license_type_id: uuid.UUID | None
    outcome: str
    filing_channels: list[str]
    explanation: str
    facts_used: dict[str, Any]
    missing_facts: list[Any]
    matched_rule_ids: list[uuid.UUID]
    conflicting_rule_ids: list[uuid.UUID]
    source_citations: list[Any]
    source_freshness_status: str
    requires_human_review: bool
    requires_counsel_review: bool
    reviewed_outcome: str | None
    reviewer_notes: str | None
    reviewed_by_actor: str | None
    reviewed_at: datetime | None
    #: Always true: the matrix is advisory and never a legal determination.
    advisory_only: bool = True


class AssessmentDetailOut(BaseModel):
    assessment: AssessmentOut
    results: list[AssessmentResultOut]
    advisory_notice: str = (
        "These results are advisory analysis for internal compliance planning. They "
        "are not legal advice and are not a determination that a licence is or is "
        "not required."
    )


class ResultReview(BaseModel):
    reviewed_outcome: str | None = None
    notes: str | None = None


class ResultOverride(BaseModel):
    overridden_outcome: str
    reason: str = Field(min_length=10, max_length=2000)
    authority: str
    source_reference: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class CounselReviewRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


# --------------------------------------------------------------------- sources


class SourceCreate(BaseModel):
    source_key: str = Field(min_length=1, max_length=120)
    source_type: str
    authority_level: str
    title: str
    jurisdiction_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    official_url: str | None = None
    access_method: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    owner_actor: str | None = None
    freshness_days: int | None = None
    citation_label: str | None = None
    notes: str | None = None


class SnapshotCreate(BaseModel):
    #: Manual snapshots must point at immutable governed storage. Inline text is
    #: optional review aid only and must match content_sha256 when both are sent.
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    content_text: str | None = None
    content_storage_uri: str | None = None
    effective_date: date | None = None
    change_summary: str | None = None


class SnapshotReview(BaseModel):
    approve: bool
    affects_rules: bool | None = None
    notes: str | None = None


class SourceOut(ORMModel):
    id: uuid.UUID
    source_key: str
    source_type: str
    authority_level: str
    title: str
    jurisdiction_id: uuid.UUID | None
    official_url: str | None
    access_method: str
    effective_date: date | None
    expiry_date: date | None
    last_verified_at: datetime | None
    verification_status: str
    current_snapshot_id: uuid.UUID | None
    owner_actor: str | None
    freshness_days: int | None
    created_at: datetime


class SnapshotOut(ORMModel):
    id: uuid.UUID
    requirement_source_id: uuid.UUID
    version: int
    content_sha256: str
    content_storage_uri: str | None
    retrieved_at: datetime
    effective_date: date | None
    change_summary: str | None
    change_details: dict[str, Any]
    previous_snapshot_id: uuid.UUID | None
    review_status: str
    reviewed_by_actor: str | None
    reviewed_at: datetime | None
    affects_rules: bool | None


# ----------------------------------------------------------------- obligations


class ObligationCreate(BaseModel):
    legal_entity_id: uuid.UUID
    obligation_type: str
    title: str
    license_id: uuid.UUID | None = None
    bond_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None
    status: str | None = None
    recurrence_rule: dict[str, Any] | None = None
    statutory_due_date: date | None = None
    next_due_date: date | None = None
    internal_start_date: date | None = None
    responsible_owner: str | None = None
    vendor_organization_id: uuid.UUID | None = None
    regulator_organization_id: uuid.UUID | None = None
    notes: str | None = None


class ObligationUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    next_due_date: date | None = None
    internal_start_date: date | None = None
    responsible_owner: str | None = None
    recurrence_rule: dict[str, Any] | None = None
    notes: str | None = None


class ObligationOut(ORMModel):
    id: uuid.UUID
    obligation_key: str
    legal_entity_id: uuid.UUID
    license_id: uuid.UUID | None
    bond_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID | None
    obligation_type: str
    title: str
    status: str
    recurrence_rule: dict[str, Any] | None
    statutory_due_date: date | None
    next_due_date: date | None
    internal_start_date: date | None
    responsible_owner: str | None
    predecessor_obligation_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------- cases


class CaseCreate(BaseModel):
    obligation_id: uuid.UUID
    assigned_owner: str | None = None
    priority: str | None = None


class CaseUpdate(BaseModel):
    assigned_owner: str | None = None
    priority: str | None = None
    internal_target_date: date | None = None
    vendor_organization_id: uuid.UUID | None = None
    regulator_organization_id: uuid.UUID | None = None
    primary_conversation_id: str | None = None


class CaseTransition(BaseModel):
    to_stage: str
    reason: str | None = None
    evidence: dict[str, Any] | None = None
    close_reason: str | None = None


class CaseOut(ORMModel):
    id: uuid.UUID
    case_key: str
    obligation_id: uuid.UUID
    legal_entity_id: uuid.UUID
    license_id: uuid.UUID | None
    bond_id: uuid.UUID | None
    task_id: uuid.UUID | None
    case_type: str
    current_stage: str
    status: str
    priority: str
    statutory_due_date: date | None
    internal_target_date: date | None
    assigned_owner: str | None
    vendor_organization_id: uuid.UUID | None
    regulator_organization_id: uuid.UUID | None
    primary_conversation_id: str | None
    close_reason: str | None
    blocked_reason: str | None
    created_by_actor: str | None
    stage_entered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CaseStageEventOut(BaseModel):
    id: str
    from_stage: str | None
    to_stage: str
    actor_id: str | None
    reason: str | None
    evidence: dict[str, Any]
    seconds_in_previous_stage: int | None
    occurred_at: str


class CaseEmailLinkOut(BaseModel):
    """A proposed or confirmed correspondence link, with its reasoning."""

    id: str
    compliance_case_id: str
    case_key: str | None = None
    email_id: str
    conversation_id: str | None
    link_status: str
    match_score: float | None
    match_reasons: dict[str, Any]
    proposed_by_actor: str | None
    proposed_at: str
    decided_by_actor: str | None
    decided_at: str | None
    decision_reason: str | None
    #: Context a reviewer needs to judge the match without opening the message.
    email_subject: str | None = None
    email_sender: str | None = None
    email_received_at: str | None = None
    legal_entity_name: str | None = None


class CaseEmailLinkDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CaseThreadMessageOut(BaseModel):
    """One message in a case's confirmed correspondence.

    Body content is deliberately excluded: the existing message endpoints own
    that, with their own redaction rules.
    """

    id: str
    conversation_id: str | None
    subject: str | None
    sender_name: str | None
    sender_email: str | None
    received_at: str | None
    processing_state: str
    has_attachments: bool
    direction: str


class RenewalTimelineEntry(BaseModel):
    """One dated event in a licence's renewal history."""

    occurred_at: str
    category: str
    summary: str
    detail: str | None = None
    actor_id: str | None = None
    case_id: str | None = None
    case_key: str | None = None
    email_id: str | None = None
    reference: dict[str, Any] = Field(default_factory=dict)


class RenewalTimelineOut(BaseModel):
    license_id: str
    license_key: str
    current_status: str
    expiration_date: str | None
    renewal_due_date: str | None
    open_case_count: int
    active_stage: str | None
    entries: list[RenewalTimelineEntry]


class InformationRequestCreate(BaseModel):
    question_text: str = Field(min_length=1, max_length=4000)
    information_definition_id: uuid.UUID | None = None
    requested_from_actor: str | None = None
    due_at: datetime | None = None
    source_email_id: uuid.UUID | None = None
    source_vendor_question: str | None = None


class InformationRequestUpdate(BaseModel):
    status: str | None = None
    requested_from_actor: str | None = None
    response_value_id: uuid.UUID | None = None
    resolution_note: str | None = None


class InformationRequestOut(ORMModel):
    id: uuid.UUID
    compliance_case_id: uuid.UUID
    information_definition_id: uuid.UUID | None
    question_text: str
    requested_from_actor: str | None
    status: str
    due_at: datetime | None
    response_value_id: uuid.UUID | None
    source_email_id: uuid.UUID | None
    source_vendor_question: str | None
    provided_to_vendor_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------- deadlines


class DeadlineUpdate(BaseModel):
    new_due_at: datetime | None = None
    assigned_owner: str | None = None
    reason: str = Field(min_length=5, max_length=500)


class DeadlineComplete(BaseModel):
    note: str | None = None


class DeadlineOut(ORMModel):
    id: uuid.UUID
    obligation_id: uuid.UUID
    compliance_case_id: uuid.UUID | None
    deadline_type: str
    due_at: datetime
    internal_target_at: datetime | None
    status: str
    severity: str
    assigned_owner: str | None
    backup_owner: str | None
    source_rule_id: uuid.UUID | None
    manually_overridden: bool
    override_reason: str | None
    last_escalation_level: str | None
    applied_adjustment: str | None
    completed_at: datetime | None
    created_at: datetime


class MaterializeRequest(BaseModel):
    obligation_id: uuid.UUID | None = None
    horizon_days: int | None = Field(default=None, ge=1, le=3650)


class CalendarEntryOut(BaseModel):
    deadline_id: str
    obligation_id: str
    compliance_case_id: str | None
    legal_entity_id: str
    jurisdiction_id: str | None
    obligation_type: str
    title: str
    deadline_type: str
    due_at: str
    internal_target_at: str | None
    status: str
    severity: str
    assigned_owner: str | None
    manually_overridden: bool
    escalation_level: str | None
    is_statutory: bool


# --------------------------------------------------------- information registry


class DefinitionCreate(BaseModel):
    information_key: str = Field(min_length=1, max_length=120)
    name: str
    category: str
    data_type: str
    sensitivity: str | None = None
    description: str | None = None
    default_owner_role: str | None = None
    validation_rules: dict[str, Any] | None = None
    reusable_policy: str | None = None
    freshness_days: int | None = None
    display_keep_last: int = Field(default=0, ge=0, le=8)


class DefinitionOut(ORMModel):
    id: uuid.UUID
    information_key: str
    name: str
    category: str
    description: str | None
    data_type: str
    sensitivity: str
    default_owner_role: str | None
    validation_rules: dict[str, Any]
    reusable_policy: str
    freshness_days: int | None
    display_keep_last: int
    is_active: bool
    created_at: datetime


class ValueCreate(BaseModel):
    information_definition_id: uuid.UUID
    value: Any
    legal_entity_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None
    license_id: uuid.UUID | None = None
    vendor_organization_id: uuid.UUID | None = None
    compliance_case_id: uuid.UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    owner_actor: str | None = None
    source_document_id: uuid.UUID | None = None
    source_reference: str | None = None


class ValueApprove(BaseModel):
    #: Requires the Manager role and an ALL_ENTITIES_APPROVED definition.
    cross_entity_approved: bool = False


class ValueReject(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class InformationValueOut(ORMModel):
    """Never carries a decrypted value; only the masked display form."""

    id: uuid.UUID
    information_definition_id: uuid.UUID
    legal_entity_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID | None
    license_id: uuid.UUID | None
    value_version: int
    display_value_redacted: str | None
    status: str
    valid_from: date | None
    valid_to: date | None
    owner_actor: str | None
    source_document_id: uuid.UUID | None
    source_reference: str | None
    created_by_actor: str | None
    approved_by_actor: str | None
    approved_at: datetime | None
    cross_entity_approved_by_actor: str | None
    superseded_by_value_id: uuid.UUID | None
    last_used_at: datetime | None
    created_at: datetime


class OwnerAssignmentCreate(BaseModel):
    owner_actor: str
    legal_entity_id: uuid.UUID | None = None
    is_primary: bool = False


# --------------------------------------------------------------------- packets


class PacketTemplateItemCreate(BaseModel):
    item_key: str = Field(min_length=1, max_length=80)
    document_type: str
    required: bool = True
    selection_policy: dict[str, Any] | None = None
    sort_order: int = 100
    instructions: str | None = None


class PacketTemplateCreate(BaseModel):
    template_key: str = Field(min_length=1, max_length=120)
    name: str
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    case_type: str | None = None
    description: str | None = None
    requirement_source_snapshot_id: uuid.UUID | None = None
    items: list[PacketTemplateItemCreate] = Field(default_factory=list)


class PacketCreate(BaseModel):
    packet_template_id: uuid.UUID


class PacketBuild(BaseModel):
    #: item_key -> document_id, for deliberate manual selection.
    overrides: dict[str, uuid.UUID] | None = None


class PacketReject(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class PacketItemOut(BaseModel):
    packet_item_key: str
    document_type: str | None
    document_id: str | None
    document_version_id: str | None
    status: str
    required: bool
    inclusion_reason: str | None
    document_sha256: str | None
    filename_in_archive: str | None
    override_by_actor: str | None
    sort_order: int


class PacketDetailOut(BaseModel):
    id: str
    packet_key: str
    compliance_case_id: str
    version: int
    status: str
    manifest_sha256: str | None
    archive_sha256: str | None
    archive_size_bytes: int | None
    archive_format: str
    archive_ready: bool
    missing_items: list[Any]
    validation_results: list[Any]
    created_by_actor: str | None
    reviewed_by_actor: str | None
    approved_at: str | None
    built_at: str | None
    items: list[PacketItemOut]


# ----------------------------------------------------------------------- forms


class FormTemplateCreate(BaseModel):
    template_key: str = Field(min_length=1, max_length=120)
    name: str
    form_family: str
    template_document_id: uuid.UUID
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    version: int = Field(default=1, ge=1)
    form_format: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    template_sha256: str | None = None


class FormTemplateOut(ORMModel):
    id: uuid.UUID
    template_key: str
    name: str
    form_family: str
    jurisdiction_id: uuid.UUID | None
    license_type_id: uuid.UUID | None
    version: int
    template_document_id: uuid.UUID
    form_format: str
    field_detection_status: str
    status: str
    detected_field_count: int | None
    inspection_notes: str | None
    effective_from: date | None
    effective_to: date | None
    created_at: datetime


class MappingUpsert(BaseModel):
    field_key: str
    source_type: str
    source_key: str | None = None
    transformation: str | None = None
    #: Approval is what permits autofill; a proposed mapping never fills a form.
    approve: bool = False


class FormInstanceCreate(BaseModel):
    form_template_id: uuid.UUID


class FormFieldSet(BaseModel):
    field_key: str
    value: str | None = None
    status: str | None = None


class FormFieldsPatch(BaseModel):
    fields: list[FormFieldSet] = Field(min_length=1)


class ApproveForSignature(BaseModel):
    approved_draft_sha256: str = Field(min_length=64, max_length=64)
    required_signatory_actor: str | None = None
    required_signatory_title: str | None = None


class RecordSignedDocument(BaseModel):
    signed_document_id: uuid.UUID
    signed_content_sha256: str = Field(min_length=64, max_length=64)
    signed_page_count: int | None = Field(default=None, ge=1)


class RecordExternalSubmission(BaseModel):
    reference: str = Field(min_length=1, max_length=300)


class FormFieldOut(BaseModel):
    field_key: str
    label: str
    field_type: str
    required: bool
    sensitivity: str
    page_number: int | None
    status: str
    display_value: str | None
    source_type: str
    source_value_version: int | None
    unresolved_reason: str | None
    reviewed_by_actor: str | None
    is_masked: bool


class FormInstanceDetailOut(BaseModel):
    id: str
    instance_key: str
    compliance_case_id: str
    form_template_id: str
    version: int
    status: str
    signature_required: bool
    signature_status: str
    required_signatory_actor: str | None
    signed_document_id: str | None
    external_submission_reference: str | None
    missing_fields: list[Any]
    validation_results: list[Any]
    field_snapshot_sha256: str | None
    approved_draft_sha256: str | None
    generated_document_id: str | None
    worksheet_document_id: str | None
    prepared_by_actor: str | None
    reviewed_by_actor: str | None
    fields: list[FormFieldOut]


# ------------------------------------------------------------ tracker imports


class TrackerImportApply(BaseModel):
    confirm: bool = False

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Applying a tracker import requires confirm=true.")
        return value


class TrackerImportPlanOut(BaseModel):
    import_run_id: str
    status: str
    mapping_required: bool
    headers: list[str] | None = None
    sheet_names: list[str] | None = None
    selected_sheet: str | None = None
    sample_rows: list[dict[str, str]] | None = None
    total_rows: int | None = None
    formula_cell_count: int | None = None
    counts: dict[str, int] | None = None
    dry_run: bool | None = None
    notes: list[str] | None = None


class TrackerImportApplyOut(BaseModel):
    import_run_id: str
    plan_run_id: str
    status: str
    inserted: int
    updated: int
    errors: int


# --------------------------------------------------------------------- taxonomy


class JurisdictionCreate(BaseModel):
    jurisdiction_key: str = Field(min_length=1, max_length=80)
    name: str
    jurisdiction_type: str
    parent_jurisdiction_id: uuid.UUID | None = None
    timezone: str | None = None


class JurisdictionOut(ORMModel):
    id: uuid.UUID
    jurisdiction_key: str
    name: str
    jurisdiction_type: str
    parent_jurisdiction_id: uuid.UUID | None
    timezone: str | None
    is_active: bool


class LicenseTypeCreate(BaseModel):
    license_type_key: str = Field(min_length=1, max_length=80)
    name: str
    category: str
    description: str | None = None


class LicenseTypeOut(ORMModel):
    id: uuid.UUID
    license_type_key: str
    name: str
    category: str
    description: str | None
    is_active: bool


class BusinessActivityOut(ORMModel):
    id: uuid.UUID
    activity_key: str
    name: str
    category: str
    description: str | None
    is_active: bool


# -------------------------------------------------------------------- dashboard


class DashboardSummaryOut(BaseModel):
    licenses_total: int
    licenses_active: int
    licenses_expiring: dict[str, int]
    obligations_overdue: int
    cases_open: int
    cases_blocked: int
    cases_overdue: int
    cases_by_stage: dict[str, int]
    information_requests_open: int
    information_values_stale: int
    forms_waiting_signature: int
    forms_waiting_information: int
    packets_missing_items: int
    sources_stale: int
    source_changes_pending: int
    assessments_counsel_review: int
    advisory_notice: str = (
        "Requirement outcomes shown anywhere in this portal are advisory and require "
        "human review. They are not legal advice."
    )


class CurrentTrackerWindowOut(BaseModel):
    value: str
    label: str


class CurrentTrackerSummaryOut(BaseModel):
    events_total: int
    due_next_30: int
    due_next_90: int
    due_this_year: int
    overdue: int
    non_licensed: int
    tracked_jurisdictions: int


class CurrentTrackerEventOut(BaseModel):
    event_id: str
    state: str
    abbreviation: str | None
    jurisdiction_type: str | None
    tracker_status: str | None
    item_type: str
    item_name: str
    due_date: date
    agency: str | None
    owner: str | None
    notes: str | None
    source_row: int
    source_cell: str
    days_remaining: int
    timing_status: str


class NonLicensedTrackerStateOut(BaseModel):
    record_id: str
    state: str
    abbreviation: str | None
    jurisdiction_type: str | None
    nmls: str | None
    reason: str | None
    comments: str | None
    source_row: int


class CurrentTrackerOut(BaseModel):
    metadata: dict[str, Any]
    as_of: date
    selected_window: str
    available_windows: list[CurrentTrackerWindowOut]
    summary: CurrentTrackerSummaryOut
    events: list[CurrentTrackerEventOut]
    non_licensed: list[NonLicensedTrackerStateOut]


class DataQualityFinding(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    entity_type: str
    entity_id: str | None
    detail: str


class DataQualityReportOut(BaseModel):
    generated_at: str
    total_findings: int
    findings_by_code: dict[str, int]
    findings: list[DataQualityFinding]
