"""Initial schema: all Milestone 1 tables, constraints, and indexes.

Reviewed and cleaned from Alembic autogenerate output.

Revision ID: 0001
Revises:
Create Date: 2026-07-21 14:21:52.597974
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('HUMAN', 'SYSTEM', 'IMPORT')", name=op.f("ck_audit_events_actor_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_correlation", "audit_events", ["correlation_id"], unique=False)
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"], unique=False
    )
    op.create_index("ix_audit_events_occurred", "audit_events", ["occurred_at"], unique=False)
    op.create_table(
        "mailboxes",
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("graph_user_id", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailboxes")),
    )
    op.create_index(
        "uq_mailboxes_address_lower",
        "mailboxes",
        [sa.literal_column("lower(address)")],
        unique=True,
    )
    op.create_table(
        "outbox_events",
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'FAILED')", name=op.f("ck_outbox_events_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
    )
    op.create_index(
        "ix_outbox_events_status_available",
        "outbox_events",
        ["status", "available_at"],
        unique=False,
    )
    op.create_table(
        "emails",
        sa.Column("mailbox_id", sa.UUID(), nullable=False),
        sa.Column("graph_message_id", sa.Text(), nullable=False),
        sa.Column("internet_message_id", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("current_graph_folder_id", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("sender_email", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_content_type", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=True),
        sa.Column("processing_state", sa.Text(), nullable=False),
        sa.Column("resume_state", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("raw_message_storage_uri", sa.Text(), nullable=True),
        sa.Column("raw_message_sha256", sa.Text(), nullable=True),
        sa.Column("source_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "processing_state IN ('DISCOVERED', 'FETCHED', 'ATTACHMENTS_SAVED', 'CLASSIFIED', 'TASK_CREATED', 'MOVED', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW')",
            name=op.f("ck_emails_processing_state"),
        ),
        sa.CheckConstraint(
            "resume_state IN ('DISCOVERED', 'FETCHED', 'ATTACHMENTS_SAVED', 'CLASSIFIED', 'TASK_CREATED', 'MOVED', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW')",
            name=op.f("ck_emails_resume_state"),
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_emails_mailbox_id_mailboxes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emails")),
        sa.UniqueConstraint("mailbox_id", "graph_message_id", name="uq_emails_graph_message"),
    )
    op.create_index("ix_emails_conversation_id", "emails", ["conversation_id"], unique=False)
    op.create_index(
        "ix_emails_next_retry_at",
        "emails",
        ["next_retry_at"],
        unique=False,
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    op.create_index(
        "ix_emails_state_received",
        "emails",
        ["mailbox_id", "processing_state", "received_at"],
        unique=False,
    )
    op.create_index(
        "uq_emails_internet_message_id",
        "emails",
        ["mailbox_id", "internet_message_id"],
        unique=True,
        postgresql_where=sa.text("internet_message_id IS NOT NULL"),
    )
    op.create_table(
        "mailbox_folders",
        sa.Column("mailbox_id", sa.UUID(), nullable=False),
        sa.Column("graph_folder_id", sa.Text(), nullable=False),
        sa.Column("parent_graph_folder_id", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("folder_path", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_mailbox_folders_mailbox_id_mailboxes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailbox_folders")),
        sa.UniqueConstraint("mailbox_id", "graph_folder_id", name="uq_mailbox_folders_graph_id"),
    )
    op.create_table(
        "classifications",
        sa.Column("email_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("email_type", sa.Text(), nullable=False),
        sa.Column(
            "states", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "license_types",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "license_numbers",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "requested_information",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "documents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("action_required", sa.Boolean(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("classification_method", sa.Text(), nullable=False),
        sa.Column(
            "rule_matches",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_provider", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("model_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email_type IN ('missing_information_request', 'renewal_notice', 'bond_correspondence', 'annual_report_or_assessment', 'invoice_or_fee', 'submission_confirmation', 'license_or_proof_received', 'regulator_correspondence', 'general_correspondence')",
            name=op.f("ck_classifications_email_type"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_classifications_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_classifications_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classifications")),
        sa.UniqueConstraint("email_id", "version", name="uq_classifications_email_version"),
    )
    op.create_index(
        "uq_classifications_current",
        "classifications",
        ["email_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "email_attachments",
        sa.Column("email_id", sa.UUID(), nullable=False),
        sa.Column("graph_attachment_id", sa.Text(), nullable=False),
        sa.Column("attachment_type", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("stored_filename", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("graph_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("stored_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_inline", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("content_id", sa.Text(), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("sha256_checksum", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DISCOVERED', 'DOWNLOADED', 'REFERENCE_NOT_DOWNLOADED', 'FAILED', 'QUARANTINED')",
            name=op.f("ck_email_attachments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_email_attachments_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_attachments")),
        sa.UniqueConstraint(
            "email_id", "graph_attachment_id", name="uq_email_attachments_graph_id"
        ),
    )
    op.create_index(
        "uq_email_attachments_dedupe",
        "email_attachments",
        ["email_id", "sha256_checksum", "original_filename"],
        unique=True,
        postgresql_where=sa.text("sha256_checksum IS NOT NULL"),
    )
    op.create_table(
        "email_processing_events",
        sa.Column("email_id", sa.UUID(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "from_state IN ('DISCOVERED', 'FETCHED', 'ATTACHMENTS_SAVED', 'CLASSIFIED', 'TASK_CREATED', 'MOVED', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW')",
            name=op.f("ck_email_processing_events_from_state"),
        ),
        sa.CheckConstraint(
            "to_state IN ('DISCOVERED', 'FETCHED', 'ATTACHMENTS_SAVED', 'CLASSIFIED', 'TASK_CREATED', 'MOVED', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW')",
            name=op.f("ck_email_processing_events_to_state"),
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_email_processing_events_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_processing_events")),
    )
    op.create_index(
        "ix_email_processing_events_correlation",
        "email_processing_events",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_processing_events_email_occurred",
        "email_processing_events",
        ["email_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "email_recipients",
        sa.Column("email_id", sa.UUID(), nullable=False),
        sa.Column("recipient_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recipient_type IN ('TO', 'CC', 'BCC', 'REPLY_TO')",
            name=op.f("ck_email_recipients_recipient_type"),
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_email_recipients_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_recipients")),
    )
    op.create_index(
        "ix_email_recipients_email_type",
        "email_recipients",
        ["email_id", "recipient_type"],
        unique=False,
    )
    op.create_table(
        "mailbox_sync_state",
        sa.Column("mailbox_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.UUID(), nullable=False),
        sa.Column("delta_link", sa.Text(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["mailbox_folders.id"],
            name=op.f("fk_mailbox_sync_state_folder_id_mailbox_folders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_mailbox_sync_state_mailbox_id_mailboxes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailbox_sync_state")),
        sa.UniqueConstraint("mailbox_id", "folder_id", name="uq_mailbox_sync_state_folder"),
    )
    op.create_table(
        "classification_reviews",
        sa.Column("classification_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reviewer_principal", sa.Text(), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column(
            "corrected_classification", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('APPROVED', 'CORRECTED', 'REJECTED')",
            name=op.f("ck_classification_reviews_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["classification_id"],
            ["classifications.id"],
            name=op.f("fk_classification_reviews_classification_id_classifications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_reviews")),
    )
    op.create_index(
        "ix_classification_reviews_classification",
        "classification_reviews",
        ["classification_id"],
        unique=False,
    )
    op.create_table(
        "licensing_tasks",
        sa.Column("task_key", sa.Text(), nullable=False),
        sa.Column("email_id", sa.UUID(), nullable=True),
        sa.Column("classification_id", sa.UUID(), nullable=True),
        sa.Column("review_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("destination_folder_name", sa.Text(), nullable=True),
        sa.Column("destination_folder_id", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("assigned_to", sa.Text(), nullable=True),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("email_type", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=True),
        sa.Column("draft_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("draft_status", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "draft_status IN ('NOT_REQUIRED', 'PENDING', 'CREATED', 'SENT', 'FAILED')",
            name=op.f("ck_licensing_tasks_draft_status"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'WAITING_FOR_INFO', 'READY_TO_SEND', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_licensing_tasks_status"),
        ),
        sa.ForeignKeyConstraint(
            ["classification_id"],
            ["classifications.id"],
            name=op.f("fk_licensing_tasks_classification_id_classifications"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_licensing_tasks_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["classification_reviews.id"],
            name=op.f("fk_licensing_tasks_review_id_classification_reviews"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_licensing_tasks")),
        sa.UniqueConstraint("task_key", name="uq_licensing_tasks_task_key"),
    )
    op.create_index("ix_licensing_tasks_due_date", "licensing_tasks", ["due_date"], unique=False)
    op.create_index("ix_licensing_tasks_email", "licensing_tasks", ["email_id"], unique=False)
    op.create_index(
        "ix_licensing_tasks_status_queue", "licensing_tasks", ["status", "queue"], unique=False
    )
    op.create_table(
        "outbound_drafts",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("mailbox_id", sa.UUID(), nullable=False),
        sa.Column("graph_draft_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "to_recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cc_recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("graph_web_link", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('NOT_REQUIRED', 'PENDING', 'CREATED', 'SENT', 'FAILED')",
            name=op.f("ck_outbound_drafts_status"),
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_outbound_drafts_mailbox_id_mailboxes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["licensing_tasks.id"],
            name=op.f("fk_outbound_drafts_task_id_licensing_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbound_drafts")),
    )
    op.create_index("ix_outbound_drafts_task", "outbound_drafts", ["task_id"], unique=False)
    op.create_table(
        "task_requested_items",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("item_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REQUESTED', 'RECEIVED', 'VERIFIED', 'NOT_APPLICABLE')",
            name=op.f("ck_task_requested_items_status"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["licensing_tasks.id"],
            name=op.f("fk_task_requested_items_task_id_licensing_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_requested_items")),
    )
    op.create_index(
        "ix_task_requested_items_task", "task_requested_items", ["task_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_task_requested_items_task", table_name="task_requested_items")
    op.drop_table("task_requested_items")
    op.drop_index("ix_outbound_drafts_task", table_name="outbound_drafts")
    op.drop_table("outbound_drafts")
    op.drop_index("ix_licensing_tasks_status_queue", table_name="licensing_tasks")
    op.drop_index("ix_licensing_tasks_email", table_name="licensing_tasks")
    op.drop_index("ix_licensing_tasks_due_date", table_name="licensing_tasks")
    op.drop_table("licensing_tasks")
    op.drop_index("ix_classification_reviews_classification", table_name="classification_reviews")
    op.drop_table("classification_reviews")
    op.drop_table("mailbox_sync_state")
    op.drop_index("ix_email_recipients_email_type", table_name="email_recipients")
    op.drop_table("email_recipients")
    op.drop_index("ix_email_processing_events_email_occurred", table_name="email_processing_events")
    op.drop_index("ix_email_processing_events_correlation", table_name="email_processing_events")
    op.drop_table("email_processing_events")
    op.drop_index(
        "uq_email_attachments_dedupe",
        table_name="email_attachments",
        postgresql_where=sa.text("sha256_checksum IS NOT NULL"),
    )
    op.drop_table("email_attachments")
    op.drop_index(
        "uq_classifications_current",
        table_name="classifications",
        postgresql_where=sa.text("is_current"),
    )
    op.drop_table("classifications")
    op.drop_table("mailbox_folders")
    op.drop_index(
        "uq_emails_internet_message_id",
        table_name="emails",
        postgresql_where=sa.text("internet_message_id IS NOT NULL"),
    )
    op.drop_index("ix_emails_state_received", table_name="emails")
    op.drop_index(
        "ix_emails_next_retry_at",
        table_name="emails",
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    op.drop_index("ix_emails_conversation_id", table_name="emails")
    op.drop_table("emails")
    op.drop_index("ix_outbox_events_status_available", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("uq_mailboxes_address_lower", table_name="mailboxes")
    op.drop_table("mailboxes")
    op.drop_index("ix_audit_events_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_correlation", table_name="audit_events")
    op.drop_table("audit_events")
