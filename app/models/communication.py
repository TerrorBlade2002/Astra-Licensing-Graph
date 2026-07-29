"""Response plans, templates, approvals, attempts, jobs, and completion records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.communications.enums import (
    ApprovalDecision,
    CommunicationJobStatus,
    CommunicationJobType,
    MoveAttemptStatus,
    ReadinessStatus,
    RecipientMode,
    ResponseType,
    SendAttemptStatus,
    TemplateVersionStatus,
    WorkflowCompletionType,
)
from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class ResponseTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "response_templates"
    __table_args__ = (enum_check("response_type", ResponseType, "response_type"),)
    template_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    response_type: Mapped[str] = mapped_column(nullable=False)
    vendor: Mapped[str | None]
    email_type: Mapped[str | None]
    jurisdiction: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )


class ResponseTemplateVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "response_template_versions"
    __table_args__ = (
        UniqueConstraint("response_template_id", "version", name="uq_response_template_version"),
        Index(
            "uq_response_template_active",
            "response_template_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        enum_check("status", TemplateVersionStatus, "template_version_status"),
    )
    response_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("response_templates.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    subject_template: Mapped[str | None]
    text_body_template: Mapped[str] = mapped_column(nullable=False)
    html_body_template: Mapped[str | None]
    allowed_variables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    validation_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    template_sha256: Mapped[str] = mapped_column(nullable=False)
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    activated_at: Mapped[datetime | None]


class ResponsePlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "response_plans"
    __table_args__ = (
        enum_check("response_type", ResponseType, "response_type"),
        enum_check("readiness_status", ReadinessStatus, "readiness_status"),
        enum_check("proposed_recipient_mode", RecipientMode, "recipient_mode"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    classification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classifications.id", ondelete="RESTRICT"), nullable=False
    )
    response_type: Mapped[str] = mapped_column(nullable=False)
    response_required: Mapped[bool] = mapped_column(nullable=False)
    readiness_status: Mapped[str] = mapped_column(nullable=False)
    readiness_blockers: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    selected_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("response_template_versions.id", ondelete="RESTRICT")
    )
    selected_signature_key: Mapped[str | None]
    suggested_subject: Mapped[str | None]
    suggested_destination_folder_name: Mapped[str | None]
    proposed_recipient_mode: Mapped[str] = mapped_column(nullable=False)
    reply_all_reviewed: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    bcc_authorized: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    bcc_authorization_reason: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    reviewed_by_actor: Mapped[str | None]


class SendApproval(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "send_approvals"
    __table_args__ = (
        Index(
            "uq_send_approvals_valid",
            "outbound_draft_id",
            unique=True,
            postgresql_where=text("decision = 'APPROVED' AND invalidated_at IS NULL"),
        ),
        enum_check("decision", ApprovalDecision, "decision"),
    )
    outbound_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="CASCADE"), nullable=False
    )
    draft_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_draft_versions.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(nullable=False)
    approver_actor: Mapped[str] = mapped_column(nullable=False)
    approval_snapshot_sha256: Mapped[str] = mapped_column(nullable=False)
    body_sha256: Mapped[str] = mapped_column(nullable=False)
    recipient_set_sha256: Mapped[str] = mapped_column(nullable=False)
    attachment_set_sha256: Mapped[str] = mapped_column(nullable=False)
    graph_draft_message_id: Mapped[str] = mapped_column(nullable=False)
    graph_change_key: Mapped[str | None]
    graph_etag: Mapped[str | None]
    approval_notes: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    rejected_at: Mapped[datetime | None]
    invalidated_at: Mapped[datetime | None]
    invalidation_reason: Mapped[str | None]


class OutboundSendAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "outbound_send_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_send_attempt_idempotency"),
        UniqueConstraint("outbound_draft_id", "attempt_number", name="uq_send_attempt_number"),
        enum_check("status", SendAttemptStatus, "status"),
    )
    outbound_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="CASCADE"), nullable=False
    )
    send_approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("send_approvals.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    pre_send_snapshot_sha256: Mapped[str] = mapped_column(nullable=False)
    graph_draft_message_id: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    http_status: Mapped[int | None]
    graph_request_id: Mapped[str | None]
    graph_client_request_id: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None]
    reconciled_at: Mapped[datetime | None]
    sent_copy_verified_at: Mapped[datetime | None]
    sent_graph_message_id: Mapped[str | None]
    sent_internet_message_id: Mapped[str | None]
    sent_parent_folder_id: Mapped[str | None]
    sent_body_sha256: Mapped[str | None]
    sent_recipient_set_sha256: Mapped[str | None]
    sent_attachment_set_sha256: Mapped[str | None]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]


class MessageMoveAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "message_move_attempts"
    __table_args__ = (
        UniqueConstraint("email_id", "attempt_number", name="uq_move_attempt_number"),
        enum_check("status", MoveAttemptStatus, "status"),
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    source_graph_message_id: Mapped[str] = mapped_column(nullable=False)
    destination_folder_id: Mapped[str] = mapped_column(nullable=False)
    destination_folder_name: Mapped[str] = mapped_column(nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    returned_graph_message_id: Mapped[str | None]
    returned_parent_folder_id: Mapped[str | None]
    http_status: Mapped[int | None]
    graph_request_id: Mapped[str | None]
    graph_client_request_id: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    moved_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]


class WorkflowCompletionRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workflow_completion_records"
    __table_args__ = (enum_check("completion_type", WorkflowCompletionType, "completion_type"),)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    response_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT")
    )
    outbound_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="RESTRICT")
    )
    send_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbound_send_attempts.id", ondelete="RESTRICT")
    )
    move_attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_move_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    completion_type: Mapped[str] = mapped_column(nullable=False)
    destination_folder_id: Mapped[str] = mapped_column(nullable=False)
    destination_folder_name: Mapped[str] = mapped_column(nullable=False)
    final_graph_message_id: Mapped[str] = mapped_column(nullable=False)
    communication_status: Mapped[str] = mapped_column(nullable=False)
    task_status_at_completion: Mapped[str] = mapped_column(nullable=False)
    completed_by_actor: Mapped[str | None]
    completed_at: Mapped[datetime] = mapped_column(nullable=False)
    completion_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class CommunicationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "communication_jobs"
    __table_args__ = (
        Index("ix_communication_jobs_claim", "status", "priority", "available_at"),
        enum_check("job_type", CommunicationJobType, "job_type"),
        enum_check("status", CommunicationJobStatus, "status"),
    )
    job_type: Mapped[str] = mapped_column(nullable=False)
    outbound_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="CASCADE")
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default=text("100")
    )
    idempotency_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]


class RecipientPolicyRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recipient_policy_rules"
    rule_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    rule_type: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    action: Mapped[str] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    reason: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
