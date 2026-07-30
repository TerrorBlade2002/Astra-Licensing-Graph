"""Governed, human-supervised portal assistance persistence."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check
from app.portals.enums import (
    AdapterStatus,
    AttestationStatus,
    AuthorizationStatus,
    AutomationLevel,
    BrowserSessionStatus,
    CredentialModel,
    HandoffStatus,
    HandoffType,
    PaymentStatus,
    PortalApprovalStatus,
    PortalDocumentStatus,
    PortalFieldSourceType,
    PortalFieldStatus,
    PortalJobStatus,
    PortalJobType,
    PortalReviewStatus,
    PortalRunStatus,
    PortalStepStatus,
    PortalStepType,
    PortalType,
    SnapshotStatus,
    SubmissionEvidenceType,
)


class PortalDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_definitions"
    __table_args__ = (
        Index("ix_portal_definitions_status", "status"),
        Index("ix_portal_definitions_hostname", "hostname"),
        enum_check("portal_type", PortalType, "portal_type"),
        enum_check("approved_automation_level", AutomationLevel, "automation_level"),
        enum_check("status", PortalApprovalStatus, "status"),
        enum_check("credential_model", CredentialModel, "credential_model"),
    )

    portal_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    portal_type: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False)
    hostname: Mapped[str] = mapped_column(nullable=False)
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jurisdictions.id", ondelete="SET NULL")
    )
    supported_filing_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    approved_automation_level: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    data_classification: Mapped[str] = mapped_column(nullable=False)
    credential_model: Mapped[str] = mapped_column(nullable=False)
    mfa_model: Mapped[str | None]
    captcha_expected: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    terms_review_required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    terms_review_expires_at: Mapped[datetime | None]
    final_submit_human_only: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    payment_human_only: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    attestation_human_only: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    signature_human_only: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_verified_at: Mapped[datetime | None]


class PortalReviewVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portal_review_versions"
    __table_args__ = (
        UniqueConstraint("portal_definition_id", "version", name="uq_portal_review_version"),
        Index(
            "uq_portal_review_active",
            "portal_definition_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        Index("ix_portal_review_validity", "valid_to", "status"),
        enum_check("status", PortalReviewStatus, "status"),
    )

    portal_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    terms_reference: Mapped[str | None]
    terms_sha256: Mapped[str | None]
    terms_effective_date: Mapped[date | None]
    allowed_actions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prohibited_actions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    approved_filing_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    approved_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    security_findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    review_notes: Mapped[str | None]
    reviewed_by_compliance: Mapped[str | None]
    reviewed_by_security: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    valid_from: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]


class PortalUserAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_user_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "portal_definition_id",
            "user_principal_id",
            name="uq_portal_user_authorization",
        ),
        Index("ix_portal_user_authorizations_status", "authorization_status", "expires_at"),
        enum_check("authorization_status", AuthorizationStatus, "authorization_status"),
    )

    portal_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_definitions.id", ondelete="CASCADE"), nullable=False
    )
    user_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_principals.id", ondelete="CASCADE"), nullable=False
    )
    external_account_reference: Mapped[str | None]
    portal_role: Mapped[str | None]
    authorization_status: Mapped[str] = mapped_column(nullable=False)
    authorized_filing_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    authorized_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    authorized_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    last_verified_at: Mapped[datetime | None]


class PortalAdapterVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portal_adapter_versions"
    __table_args__ = (
        UniqueConstraint(
            "portal_definition_id",
            "adapter_key",
            "version",
            name="uq_portal_adapter_version",
        ),
        Index(
            "uq_portal_adapter_active",
            "portal_definition_id",
            "adapter_key",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        enum_check("status", AdapterStatus, "status"),
    )

    portal_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_definitions.id", ondelete="CASCADE"), nullable=False
    )
    adapter_key: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    supported_routes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    locator_contract: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    field_mapping_version: Mapped[str | None]
    test_fixture_version: Mapped[str | None]
    source_revision: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    activated_at: Mapped[datetime | None]


class PortalFieldMapping(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portal_field_mappings"
    __table_args__ = (
        UniqueConstraint(
            "portal_adapter_version_id",
            "filing_type",
            "portal_field_key",
            name="uq_portal_field_mapping",
        ),
        Index("ix_portal_field_mapping_order", "portal_adapter_version_id", "sort_order"),
        enum_check("source_type", PortalFieldSourceType, "source_type"),
    )

    portal_adapter_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_adapter_versions.id", ondelete="CASCADE"), nullable=False
    )
    filing_type: Mapped[str] = mapped_column(nullable=False)
    portal_field_key: Mapped[str] = mapped_column(nullable=False)
    portal_label: Mapped[str | None]
    locator_strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str] = mapped_column(nullable=False)
    source_key: Mapped[str | None]
    transformation_key: Mapped[str | None]
    required: Mapped[bool] = mapped_column(nullable=False)
    sensitivity: Mapped[str] = mapped_column(nullable=False)
    human_only: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    requires_fresh_confirmation: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    allowed_values: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    validation_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PortalRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_runs"
    __table_args__ = (
        Index("ix_portal_runs_queue", "status", "deadline_at"),
        Index("ix_portal_runs_case", "compliance_case_id"),
        Index("ix_portal_runs_operator", "assigned_operator_id", "status"),
        enum_check("automation_level", AutomationLevel, "automation_level"),
        enum_check("status", PortalRunStatus, "status"),
    )

    run_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    portal_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    portal_review_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_review_versions.id", ondelete="RESTRICT"), nullable=False
    )
    portal_adapter_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_adapter_versions.id", ondelete="RESTRICT")
    )
    compliance_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_cases.id", ondelete="RESTRICT"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    license_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("license_inventory.id", ondelete="SET NULL")
    )
    form_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_instances.id", ondelete="SET NULL")
    )
    document_packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_packets.id", ondelete="SET NULL")
    )
    filing_type: Mapped[str] = mapped_column(nullable=False)
    automation_level: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    current_stage: Mapped[str] = mapped_column(nullable=False)
    assigned_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_principals.id", ondelete="SET NULL")
    )
    assigned_signatory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_principals.id", ondelete="SET NULL")
    )
    assigned_payment_approver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_principals.id", ondelete="SET NULL")
    )
    earliest_start_at: Mapped[datetime | None]
    deadline_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    created_by_actor: Mapped[str | None]


class BrowserSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        Index(
            "uq_browser_sessions_active_run",
            "portal_run_id",
            unique=True,
            postgresql_where=text(
                "session_status IN "
                "('REQUESTED','STARTING','ACTIVE_AUTOMATION','ACTIVE_HUMAN_CONTROL','PAUSED')"
            ),
        ),
        Index("ix_browser_sessions_expiry", "session_status", "expires_at"),
        enum_check("session_status", BrowserSessionStatus, "session_status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    operator_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_principals.id", ondelete="RESTRICT"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(nullable=False)
    session_status: Mapped[str] = mapped_column(nullable=False)
    browser_type: Mapped[str] = mapped_column(nullable=False)
    ephemeral_profile_id: Mapped[str] = mapped_column(nullable=False)
    encrypted_session_reference: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None]


class PortalRunStep(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portal_run_steps"
    __table_args__ = (
        UniqueConstraint("portal_run_id", "sequence_number", name="uq_portal_run_step_sequence"),
        Index("ix_portal_run_steps_timeline", "portal_run_id", "sequence_number"),
        enum_check("step_type", PortalStepType, "step_type"),
        enum_check("status", PortalStepStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    automation_mode: Mapped[str] = mapped_column(nullable=False)
    page_category: Mapped[str | None]
    safe_url_path: Mapped[str | None]
    locator_contract_version: Mapped[str | None]
    expected_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    observed_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_summary: Mapped[str | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    operator_actor: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]


class PortalRunField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_run_fields"
    __table_args__ = (
        UniqueConstraint("portal_run_id", "portal_field_key", name="uq_portal_run_field"),
        Index("ix_portal_run_fields_status", "portal_run_id", "status"),
        enum_check("status", PortalFieldStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    portal_field_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_field_mappings.id", ondelete="SET NULL")
    )
    portal_field_key: Mapped[str] = mapped_column(nullable=False)
    label: Mapped[str | None]
    approved_source_type: Mapped[str | None]
    approved_source_record_id: Mapped[uuid.UUID | None]
    approved_value_fingerprint: Mapped[str | None]
    entered_value_fingerprint: Mapped[str | None]
    displayed_value_redacted: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    entered_by: Mapped[str | None]
    entered_at: Mapped[datetime | None]
    verified_by: Mapped[str | None]
    verified_at: Mapped[datetime | None]
    discrepancy_code: Mapped[str | None]
    discrepancy_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class PortalRunDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_run_documents"
    __table_args__ = (
        UniqueConstraint(
            "portal_run_id", "document_version_id", name="uq_portal_run_document_version"
        ),
        Index("ix_portal_run_documents_status", "portal_run_id", "status"),
        enum_check("status", PortalDocumentStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    expected_filename: Mapped[str] = mapped_column(nullable=False)
    expected_sha256: Mapped[str] = mapped_column(nullable=False)
    portal_document_category: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    portal_upload_reference: Mapped[str | None]
    portal_display_name: Mapped[str | None]
    portal_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    selected_by_actor: Mapped[str | None]
    uploaded_by: Mapped[str | None]
    uploaded_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]
    discrepancy_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class HumanHandoff(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "human_handoffs"
    __table_args__ = (
        Index("ix_human_handoffs_queue", "status", "requested_from_user_id", "expires_at"),
        enum_check("handoff_type", HandoffType, "handoff_type"),
        enum_check("status", HandoffStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    browser_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="SET NULL")
    )
    handoff_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    requested_from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_principals.id", ondelete="SET NULL")
    )
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    result: Mapped[str | None]
    operator_confirmation: Mapped[str | None]
    evidence_reference: Mapped[str | None]
    expires_at: Mapped[datetime | None]


class PreSubmissionSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "pre_submission_snapshots"
    __table_args__ = (
        UniqueConstraint("portal_run_id", "version", name="uq_pre_submission_snapshot_version"),
        Index(
            "uq_pre_submission_snapshot_approved",
            "portal_run_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        enum_check("status", SnapshotStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    form_instance_version: Mapped[int | None]
    field_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    document_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    portal_validation_messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    discrepancy_report: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    screenshot_manifest: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    snapshot_sha256: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    created_by_actor: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]
    reviewed_at: Mapped[datetime | None]


class PortalAttestationRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portal_attestation_records"
    __table_args__ = (
        Index("ix_portal_attestation_run", "portal_run_id", "status"),
        enum_check("status", AttestationStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    attestation_type: Mapped[str] = mapped_column(nullable=False)
    required_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_principals.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    attestation_text_fingerprint: Mapped[str | None]
    displayed_text_reference: Mapped[str | None]
    completed_by_actor: Mapped[str | None]
    completed_at: Mapped[datetime | None]
    evidence_reference: Mapped[str | None]


class PortalPaymentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_payment_records"
    __table_args__ = (
        UniqueConstraint("portal_run_id", name="uq_portal_payment_run"),
        enum_check("status", PaymentStatus, "status"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(nullable=False)
    expected_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None]
    portal_fee_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approved_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    paid_by_actor: Mapped[str | None]
    paid_at: Mapped[datetime | None]
    payment_reference_redacted: Mapped[str | None]
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )


class SubmissionEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "submission_evidence"
    __table_args__ = (
        Index("ix_submission_evidence_run", "portal_run_id", "evidence_type"),
        enum_check("evidence_type", SubmissionEvidenceType, "evidence_type"),
    )

    portal_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(nullable=False)
    confirmation_number: Mapped[str | None]
    filing_reference: Mapped[str | None]
    submission_status: Mapped[str | None]
    submitted_by_actor: Mapped[str | None]
    submitted_at: Mapped[datetime | None]
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    screenshot_storage_uri: Mapped[str | None]
    receipt_storage_uri: Mapped[str | None]
    evidence_sha256: Mapped[str | None]
    evidence_verified_by_actor: Mapped[str | None]
    verified_at: Mapped[datetime | None]
    notes: Mapped[str | None]


class PortalJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "portal_jobs"
    __table_args__ = (
        Index("ix_portal_jobs_claim", "status", "available_at", "priority"),
        Index("ix_portal_jobs_lease", "lease_expires_at"),
        enum_check("job_type", PortalJobType, "job_type"),
        enum_check("status", PortalJobStatus, "status"),
    )

    job_type: Mapped[str] = mapped_column(nullable=False)
    portal_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_runs.id", ondelete="CASCADE")
    )
    browser_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    idempotency_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]
