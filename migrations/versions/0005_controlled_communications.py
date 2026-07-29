"""Controlled response drafting, approval, send, reconciliation, and routing.

Revision ID: 0005_controlled_communications
Revises: 0004_classification_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_controlled_communications"
down_revision: str | None = "0004_classification_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _json(name: str, default: str = "'[]'::jsonb", nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default),
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column(
        "licensing_tasks",
        sa.Column("communication_status", sa.Text(), server_default="NOT_STARTED", nullable=False),
    )

    op.create_table(
        "response_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("template_key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text()),
        sa.Column("email_type", sa.Text()),
        sa.Column("jurisdiction", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "response_type IN ('ACKNOWLEDGEMENT','INFORMATION_RESPONSE','DOCUMENT_RESPONSE',"
            "'CLARIFICATION_RESPONSE','PAYMENT_CONFIRMATION','FILING_CONFIRMATION',"
            "'REGULATOR_RESPONSE','BOND_RESPONSE','INTERNAL_FORWARD','NO_RESPONSE_REQUIRED')",
            name="ck_response_templates_response_type",
        ),
    )
    op.create_table(
        "response_template_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "response_template_id",
            sa.Uuid(),
            sa.ForeignKey("response_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("subject_template", sa.Text()),
        sa.Column("text_body_template", sa.Text(), nullable=False),
        sa.Column("html_body_template", sa.Text()),
        _json("allowed_variables"),
        _json("validation_rules", "'{}'::jsonb"),
        sa.Column("template_sha256", sa.Text(), nullable=False),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("approved_by_actor", sa.Text()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        _created(),
        sa.UniqueConstraint("response_template_id", "version", name="uq_response_template_version"),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','RETIRED')",
            name="ck_response_template_versions_template_version_status",
        ),
    )
    op.create_index(
        "uq_response_template_active",
        "response_template_versions",
        ["response_template_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "response_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("licensing_tasks.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "email_id",
            sa.Uuid(),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "classification_id",
            sa.Uuid(),
            sa.ForeignKey("classifications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("response_type", sa.Text(), nullable=False),
        sa.Column("response_required", sa.Boolean(), nullable=False),
        sa.Column("readiness_status", sa.Text(), nullable=False),
        _json("readiness_blockers"),
        sa.Column(
            "selected_template_version_id",
            sa.Uuid(),
            sa.ForeignKey("response_template_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column("selected_signature_key", sa.Text()),
        sa.Column("suggested_subject", sa.Text()),
        sa.Column("suggested_destination_folder_name", sa.Text()),
        sa.Column("proposed_recipient_mode", sa.Text(), nullable=False),
        sa.Column(
            "reply_all_reviewed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("bcc_authorized", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("bcc_authorization_reason", sa.Text()),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("reviewed_by_actor", sa.Text()),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "response_type IN ('ACKNOWLEDGEMENT','INFORMATION_RESPONSE','DOCUMENT_RESPONSE',"
            "'CLARIFICATION_RESPONSE','PAYMENT_CONFIRMATION','FILING_CONFIRMATION',"
            "'REGULATOR_RESPONSE','BOND_RESPONSE','INTERNAL_FORWARD','NO_RESPONSE_REQUIRED')",
            name="ck_response_plans_response_type",
        ),
        sa.CheckConstraint(
            "readiness_status IN ('NOT_REQUIRED','NOT_READY','READY_FOR_DRAFT',"
            "'READY_FOR_APPROVAL','READY_TO_SEND','BLOCKED')",
            name="ck_response_plans_readiness_status",
        ),
        sa.CheckConstraint(
            "proposed_recipient_mode IN ('REPLY','REPLY_ALL','MANUAL','INTERNAL_FORWARD','NONE')",
            name="ck_response_plans_recipient_mode",
        ),
    )

    op.drop_constraint(op.f("ck_outbound_drafts_status"), "outbound_drafts", type_="check")
    op.alter_column("outbound_drafts", "status", new_column_name="draft_status")
    op.execute(
        """UPDATE outbound_drafts SET draft_status = CASE draft_status
        WHEN 'PENDING' THEN 'LOCAL_DRAFT' WHEN 'CREATED' THEN 'GRAPH_DRAFT_CREATED'
        WHEN 'SENT' THEN 'SENT_COPY_VERIFIED' WHEN 'FAILED' THEN 'SEND_FAILED_REVIEW'
        ELSE 'CANCELLED' END"""
    )
    op.execute("UPDATE outbound_drafts SET subject = 'Imported response' WHERE subject IS NULL")
    op.alter_column("outbound_drafts", "subject", nullable=False)
    op.add_column("outbound_drafts", sa.Column("response_plan_id", sa.Uuid()))
    op.add_column("outbound_drafts", sa.Column("email_id", sa.Uuid()))
    op.add_column("outbound_drafts", sa.Column("current_version_id", sa.Uuid()))
    op.add_column("outbound_drafts", sa.Column("graph_change_key", sa.Text()))
    op.add_column("outbound_drafts", sa.Column("graph_etag", sa.Text()))
    op.add_column("outbound_drafts", sa.Column("graph_parent_folder_id", sa.Text()))
    op.add_column("outbound_drafts", _json("bcc_recipients"))
    op.add_column("outbound_drafts", _json("reply_to_recipients"))
    op.add_column(
        "outbound_drafts",
        sa.Column("local_revision", sa.Integer(), server_default="1", nullable=False),
    )
    for name in ("body_sha256", "recipient_set_sha256", "attachment_set_sha256"):
        op.add_column(
            "outbound_drafts", sa.Column(name, sa.Text(), server_default="", nullable=False)
        )
    op.add_column("outbound_drafts", sa.Column("approval_snapshot_sha256", sa.Text()))
    op.add_column("outbound_drafts", sa.Column("created_by_actor", sa.Text()))
    op.add_column("outbound_drafts", sa.Column("last_edited_by_actor", sa.Text()))
    op.add_column(
        "outbound_drafts", sa.Column("submitted_for_approval_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "outbound_drafts", sa.Column("graph_draft_created_at", sa.DateTime(timezone=True))
    )
    op.add_column("outbound_drafts", sa.Column("graph_last_synced_at", sa.DateTime(timezone=True)))
    op.add_column("outbound_drafts", sa.Column("send_queued_at", sa.DateTime(timezone=True)))
    op.add_column(
        "outbound_drafts",
        sa.Column("delivery_status", sa.Text(), server_default="NOT_APPLICABLE", nullable=False),
    )
    op.create_foreign_key(
        "fk_outbound_drafts_response_plan",
        "outbound_drafts",
        "response_plans",
        ["response_plan_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_outbound_drafts_email",
        "outbound_drafts",
        "emails",
        ["email_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_outbound_drafts_draft_status",
        "outbound_drafts",
        "draft_status IN ('LOCAL_DRAFT','GRAPH_DRAFT_PENDING','GRAPH_DRAFT_CREATED','REVIEW_IN_PROGRESS','CHANGES_REQUESTED','PENDING_SEND_APPROVAL','APPROVED_TO_SEND','SEND_QUEUED','SENDING','SEND_ACCEPTED','SEND_AMBIGUOUS','SENT_COPY_VERIFIED','SEND_FAILED_RETRYABLE','SEND_FAILED_REVIEW','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_outbound_drafts_delivery_status",
        "outbound_drafts",
        "delivery_status IN ('NOT_APPLICABLE','UNKNOWN','NO_NDR_OBSERVED',"
        "'NDR_RECEIVED','DELIVERY_CONFIRMED')",
    )
    op.create_index("ix_outbound_drafts_status", "outbound_drafts", ["draft_status", "updated_at"])

    op.create_table(
        "outbound_draft_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "outbound_draft_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        _json("to_recipients"),
        _json("cc_recipients"),
        _json("bcc_recipients"),
        _json("attachment_manifest"),
        sa.Column("body_sha256", sa.Text(), nullable=False),
        sa.Column("recipient_set_sha256", sa.Text(), nullable=False),
        sa.Column("attachment_set_sha256", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text()),
        sa.Column("created_by_actor", sa.Text()),
        _created(),
        sa.UniqueConstraint("outbound_draft_id", "revision", name="uq_draft_versions_revision"),
        sa.UniqueConstraint(
            "outbound_draft_id", "snapshot_sha256", name="uq_draft_versions_snapshot"
        ),
    )
    op.create_foreign_key(
        "fk_outbound_drafts_current_version",
        "outbound_drafts",
        "outbound_draft_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_table(
        "outbound_draft_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "outbound_draft_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "source_attachment_id",
            sa.Uuid(),
            sa.ForeignKey("email_attachments.id", ondelete="RESTRICT"),
        ),
        sa.Column("graph_attachment_id", sa.Text()),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("upload_method", sa.Text()),
        sa.Column("added_by_actor", sa.Text()),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graph_uploaded_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "status IN ('SELECTED','VALIDATED','GRAPH_UPLOAD_PENDING','GRAPH_UPLOADED',"
            "'FAILED_RETRYABLE','FAILED_REVIEW','REMOVED')",
            name="ck_outbound_draft_attachments_status",
        ),
    )
    op.create_index(
        "ix_draft_attachments_draft",
        "outbound_draft_attachments",
        ["outbound_draft_id", "status"],
    )

    op.create_table(
        "send_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "outbound_draft_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_version_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_draft_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("approver_actor", sa.Text(), nullable=False),
        sa.Column("approval_snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.Text(), nullable=False),
        sa.Column("recipient_set_sha256", sa.Text(), nullable=False),
        sa.Column("attachment_set_sha256", sa.Text(), nullable=False),
        sa.Column("graph_draft_message_id", sa.Text(), nullable=False),
        sa.Column("graph_change_key", sa.Text()),
        sa.Column("graph_etag", sa.Text()),
        sa.Column("approval_notes", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("invalidation_reason", sa.Text()),
        _created(),
        sa.CheckConstraint(
            "decision IN ('PENDING_SECOND_APPROVAL','APPROVED','REJECTED',"
            "'CHANGES_REQUESTED','INVALIDATED')",
            name="ck_send_approvals_decision",
        ),
    )
    op.create_index(
        "uq_send_approvals_valid",
        "send_approvals",
        ["outbound_draft_id"],
        unique=True,
        postgresql_where=sa.text("decision = 'APPROVED' AND invalidated_at IS NULL"),
    )
    op.create_table(
        "outbound_send_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "outbound_draft_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "send_approval_id",
            sa.Uuid(),
            sa.ForeignKey("send_approvals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("pre_send_snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("graph_draft_message_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("graph_request_id", sa.Text()),
        sa.Column("graph_client_request_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("sent_copy_verified_at", sa.DateTime(timezone=True)),
        sa.Column("sent_graph_message_id", sa.Text()),
        sa.Column("sent_internet_message_id", sa.Text()),
        sa.Column("sent_parent_folder_id", sa.Text()),
        sa.Column("sent_body_sha256", sa.Text()),
        sa.Column("sent_recipient_set_sha256", sa.Text()),
        sa.Column("sent_attachment_set_sha256", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        _created(),
        sa.UniqueConstraint("idempotency_key", name="uq_send_attempt_idempotency"),
        sa.UniqueConstraint("outbound_draft_id", "attempt_number", name="uq_send_attempt_number"),
        sa.CheckConstraint(
            "status IN ('STARTED','ACCEPTED','AMBIGUOUS','SENT_COPY_VERIFIED',"
            "'FAILED_RETRYABLE','FAILED_REVIEW','CANCELLED')",
            name="ck_outbound_send_attempts_status",
        ),
    )
    op.create_table(
        "message_move_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "email_id", sa.Uuid(), sa.ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("licensing_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_graph_message_id", sa.Text(), nullable=False),
        sa.Column("destination_folder_id", sa.Text(), nullable=False),
        sa.Column("destination_folder_name", sa.Text(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("returned_graph_message_id", sa.Text()),
        sa.Column("returned_parent_folder_id", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("graph_request_id", sa.Text()),
        sa.Column("graph_client_request_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("moved_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        _created(),
        sa.UniqueConstraint("email_id", "attempt_number", name="uq_move_attempt_number"),
        sa.CheckConstraint(
            "status IN ('STARTED','MOVED','VERIFIED','AMBIGUOUS',"
            "'FAILED_RETRYABLE','FAILED_REVIEW')",
            name="ck_message_move_attempts_status",
        ),
    )
    op.create_table(
        "communication_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column(
            "outbound_draft_id", sa.Uuid(), sa.ForeignKey("outbound_drafts.id", ondelete="CASCADE")
        ),
        sa.Column("email_id", sa.Uuid(), sa.ForeignKey("emails.id", ondelete="CASCADE")),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("licensing_tasks.id", ondelete="CASCADE")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        _json("payload", "'{}'::jsonb"),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("correlation_id", sa.Uuid()),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "job_type IN ('CREATE_GRAPH_DRAFT','SYNC_GRAPH_DRAFT','UPLOAD_DRAFT_ATTACHMENTS',"
            "'SEND_DRAFT','RECONCILE_SEND','MOVE_SOURCE_MESSAGE','VERIFY_SOURCE_MOVE',"
            "'COMPLETE_EMAIL_WORKFLOW','RECONCILE_GRAPH_DRAFT')",
            name="ck_communication_jobs_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED_RETRYABLE',"
            "'FAILED_REVIEW','CANCELLED')",
            name="ck_communication_jobs_status",
        ),
    )
    op.create_index(
        "ix_communication_jobs_claim", "communication_jobs", ["status", "priority", "available_at"]
    )
    op.create_table(
        "recipient_policy_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("rule_key", sa.Text(), nullable=False, unique=True),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        _json("conditions", "'{}'::jsonb"),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("approved_by_actor", sa.Text()),
        _created(),
        _updated(),
    )
    op.create_table(
        "workflow_completion_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "email_id",
            sa.Uuid(),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("licensing_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "response_plan_id", sa.Uuid(), sa.ForeignKey("response_plans.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "outbound_draft_id", sa.Uuid(), sa.ForeignKey("outbound_drafts.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "send_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("outbound_send_attempts.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "move_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("message_move_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("completion_type", sa.Text(), nullable=False),
        sa.Column("destination_folder_id", sa.Text(), nullable=False),
        sa.Column("destination_folder_name", sa.Text(), nullable=False),
        sa.Column("final_graph_message_id", sa.Text(), nullable=False),
        sa.Column("communication_status", sa.Text(), nullable=False),
        sa.Column("task_status_at_completion", sa.Text(), nullable=False),
        sa.Column("completed_by_actor", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        _json("metadata", "'{}'::jsonb"),
        _created(),
        sa.CheckConstraint(
            "completion_type IN ('RESPONSE_SENT_AND_ROUTED',"
            "'NO_RESPONSE_REQUIRED_AND_ROUTED','ACKNOWLEDGEMENT_SENT_AND_ROUTED',"
            "'MANUAL_COMMUNICATION_CONFIRMED_AND_ROUTED')",
            name="ck_workflow_completion_records_completion_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_completion_records")
    op.drop_table("recipient_policy_rules")
    op.drop_index("ix_communication_jobs_claim", table_name="communication_jobs")
    op.drop_table("communication_jobs")
    op.drop_table("message_move_attempts")
    op.drop_table("outbound_send_attempts")
    op.drop_index("uq_send_approvals_valid", table_name="send_approvals")
    op.drop_table("send_approvals")
    op.drop_index("ix_draft_attachments_draft", table_name="outbound_draft_attachments")
    op.drop_table("outbound_draft_attachments")
    op.drop_constraint("fk_outbound_drafts_current_version", "outbound_drafts", type_="foreignkey")
    op.drop_table("outbound_draft_versions")
    op.drop_index("ix_outbound_drafts_status", table_name="outbound_drafts")
    op.drop_constraint("ck_outbound_drafts_delivery_status", "outbound_drafts", type_="check")
    op.drop_constraint("ck_outbound_drafts_draft_status", "outbound_drafts", type_="check")
    op.drop_constraint("fk_outbound_drafts_email", "outbound_drafts", type_="foreignkey")
    op.drop_constraint("fk_outbound_drafts_response_plan", "outbound_drafts", type_="foreignkey")
    for name in (
        "delivery_status",
        "send_queued_at",
        "graph_last_synced_at",
        "graph_draft_created_at",
        "submitted_for_approval_at",
        "last_edited_by_actor",
        "created_by_actor",
        "approval_snapshot_sha256",
        "attachment_set_sha256",
        "recipient_set_sha256",
        "body_sha256",
        "local_revision",
        "reply_to_recipients",
        "bcc_recipients",
        "graph_parent_folder_id",
        "graph_etag",
        "graph_change_key",
        "current_version_id",
        "email_id",
        "response_plan_id",
    ):
        op.drop_column("outbound_drafts", name)
    op.execute(
        """UPDATE outbound_drafts SET draft_status = CASE draft_status
        WHEN 'LOCAL_DRAFT' THEN 'PENDING' WHEN 'GRAPH_DRAFT_CREATED' THEN 'CREATED'
        WHEN 'SENT_COPY_VERIFIED' THEN 'SENT' ELSE 'FAILED' END"""
    )
    op.alter_column("outbound_drafts", "draft_status", new_column_name="status")
    op.create_check_constraint(
        op.f("ck_outbound_drafts_status"),
        "outbound_drafts",
        "status IN ('NOT_REQUIRED','PENDING','CREATED','SENT','FAILED')",
    )
    op.alter_column("outbound_drafts", "subject", nullable=True)
    op.drop_table("response_plans")
    op.drop_index("uq_response_template_active", table_name="response_template_versions")
    op.drop_table("response_template_versions")
    op.drop_table("response_templates")
    op.drop_column("licensing_tasks", "communication_status")
