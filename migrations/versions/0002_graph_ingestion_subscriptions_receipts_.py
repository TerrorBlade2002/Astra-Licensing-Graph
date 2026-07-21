"""Graph ingestion: subscriptions, receipts, jobs, heartbeats, sync/email columns.

Reviewed and cleaned from Alembic autogenerate output.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21 14:59:26.785126
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("worker_type", sa.Text(), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_table(
        "graph_jobs",
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("mailbox_id", sa.UUID(), nullable=True),
        sa.Column("folder_id", sa.UUID(), nullable=True),
        sa.Column("email_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
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
            "job_type IN ('ENSURE_SUBSCRIPTION', 'RENEW_SUBSCRIPTION', 'RECREATE_SUBSCRIPTION', 'SYNC_FOLDER', 'INGEST_EMAIL')",
            name=op.f("ck_graph_jobs_job_type"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_REVIEW', 'CANCELLED')",
            name=op.f("ck_graph_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_graph_jobs_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["mailbox_folders.id"],
            name=op.f("fk_graph_jobs_folder_id_mailbox_folders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_graph_jobs_mailbox_id_mailboxes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_jobs")),
        sa.UniqueConstraint("idempotency_key", name="uq_graph_jobs_idempotency_key"),
    )
    op.create_index(
        "ix_graph_jobs_claim", "graph_jobs", ["status", "available_at", "priority"], unique=False
    )
    op.create_index("ix_graph_jobs_email", "graph_jobs", ["email_id"], unique=False)
    op.create_index("ix_graph_jobs_lease_expires", "graph_jobs", ["lease_expires_at"], unique=False)
    op.create_index(
        "ix_graph_jobs_mailbox_folder", "graph_jobs", ["mailbox_id", "folder_id"], unique=False
    )
    op.create_index(
        "uq_graph_jobs_active_ingest_email",
        "graph_jobs",
        ["email_id"],
        unique=True,
        postgresql_where=sa.text("job_type = 'INGEST_EMAIL' AND status IN ('PENDING', 'RUNNING')"),
    )
    op.create_index(
        "uq_graph_jobs_active_sync_folder",
        "graph_jobs",
        ["folder_id"],
        unique=True,
        postgresql_where=sa.text("job_type = 'SYNC_FOLDER' AND status IN ('PENDING', 'RUNNING')"),
    )
    op.create_table(
        "graph_subscriptions",
        sa.Column("mailbox_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.UUID(), nullable=False),
        sa.Column("graph_subscription_id", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("change_types", sa.Text(), nullable=False),
        sa.Column("notification_url", sa.Text(), nullable=False),
        sa.Column("lifecycle_notification_url", sa.Text(), nullable=False),
        sa.Column("client_state_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expiration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_lifecycle_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauthorization_required_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
            "status IN ('CREATING', 'ACTIVE', 'RENEWAL_REQUIRED', 'REAUTHORIZATION_REQUIRED', 'REMOVED', 'EXPIRED', 'ERROR')",
            name=op.f("ck_graph_subscriptions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["mailbox_folders.id"],
            name=op.f("fk_graph_subscriptions_folder_id_mailbox_folders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["mailboxes.id"],
            name=op.f("fk_graph_subscriptions_mailbox_id_mailboxes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_subscriptions")),
    )
    op.create_index(
        "ix_graph_subscriptions_mailbox_folder",
        "graph_subscriptions",
        ["mailbox_id", "folder_id"],
        unique=False,
    )
    op.create_index(
        "uq_graph_subscriptions_active_folder",
        "graph_subscriptions",
        ["mailbox_id", "folder_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('CREATING', 'ACTIVE', 'RENEWAL_REQUIRED', 'REAUTHORIZATION_REQUIRED')"
        ),
    )
    op.create_index(
        "uq_graph_subscriptions_graph_id",
        "graph_subscriptions",
        ["graph_subscription_id"],
        unique=True,
        postgresql_where=sa.text("graph_subscription_id IS NOT NULL"),
    )
    op.create_table(
        "graph_notification_receipts",
        sa.Column("graph_subscription_db_id", sa.UUID(), nullable=True),
        sa.Column("graph_subscription_id", sa.Text(), nullable=False),
        sa.Column("graph_notification_id", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("change_type", sa.Text(), nullable=True),
        sa.Column("lifecycle_event", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("client_state_valid", sa.Boolean(), nullable=False),
        sa.Column("processing_status", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "processing_status IN ('ACCEPTED', 'DUPLICATE', 'INVALID_CLIENT_STATE', 'UNKNOWN_SUBSCRIPTION', 'MALFORMED')",
            name=op.f("ck_graph_notification_receipts_processing_status"),
        ),
        sa.ForeignKeyConstraint(
            ["graph_subscription_db_id"],
            ["graph_subscriptions.id"],
            name=op.f(
                "fk_graph_notification_receipts_graph_subscription_db_id_graph_subscriptions"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_notification_receipts")),
        sa.UniqueConstraint("idempotency_key", name="uq_graph_notification_receipts_idem"),
    )
    op.create_index(
        "ix_graph_notification_receipts_status",
        "graph_notification_receipts",
        ["processing_status", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_graph_notification_receipts_sub",
        "graph_notification_receipts",
        ["graph_subscription_id", "received_at"],
        unique=False,
    )
    op.add_column(
        "emails", sa.Column("last_graph_modified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("emails", sa.Column("graph_etag", sa.Text(), nullable=True))
    op.add_column(
        "emails",
        sa.Column(
            "synced_folder_membership",
            sa.Text(),
            server_default=sa.text("'PRESENT'"),
            nullable=False,
        ),
    )
    op.add_column(
        "emails",
        sa.Column("removed_from_synced_folder_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("emails", sa.Column("full_message_json_storage_uri", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("full_message_json_sha256", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("raw_mime_storage_uri", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("raw_mime_sha256", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("ingestion_job_id", sa.UUID(), nullable=True))
    op.add_column(
        "emails", sa.Column("evidence_saved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "mailbox_sync_state",
        sa.Column(
            "needs_rebaseline", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "mailbox_sync_state", sa.Column("last_delta_url_fingerprint", sa.Text(), nullable=True)
    )
    op.add_column("mailbox_sync_state", sa.Column("last_page_count", sa.Integer(), nullable=True))
    op.add_column("mailbox_sync_state", sa.Column("last_change_count", sa.Integer(), nullable=True))
    op.add_column(
        "mailbox_sync_state", sa.Column("last_successful_job_id", sa.UUID(), nullable=True)
    )
    op.add_column("mailbox_sync_state", sa.Column("last_failed_job_id", sa.UUID(), nullable=True))
    op.create_check_constraint(
        "ck_emails_synced_folder_membership",
        "emails",
        "synced_folder_membership IN ('PRESENT', 'REMOVED', 'UNKNOWN')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_emails_synced_folder_membership", "emails", type_="check")
    op.drop_column("mailbox_sync_state", "last_failed_job_id")
    op.drop_column("mailbox_sync_state", "last_successful_job_id")
    op.drop_column("mailbox_sync_state", "last_change_count")
    op.drop_column("mailbox_sync_state", "last_page_count")
    op.drop_column("mailbox_sync_state", "last_delta_url_fingerprint")
    op.drop_column("mailbox_sync_state", "needs_rebaseline")
    op.drop_column("emails", "evidence_saved_at")
    op.drop_column("emails", "ingestion_job_id")
    op.drop_column("emails", "raw_mime_sha256")
    op.drop_column("emails", "raw_mime_storage_uri")
    op.drop_column("emails", "full_message_json_sha256")
    op.drop_column("emails", "full_message_json_storage_uri")
    op.drop_column("emails", "removed_from_synced_folder_at")
    op.drop_column("emails", "synced_folder_membership")
    op.drop_column("emails", "graph_etag")
    op.drop_column("emails", "last_graph_modified_at")
    op.drop_index("ix_graph_notification_receipts_sub", table_name="graph_notification_receipts")
    op.drop_index("ix_graph_notification_receipts_status", table_name="graph_notification_receipts")
    op.drop_table("graph_notification_receipts")
    op.drop_index(
        "uq_graph_subscriptions_graph_id",
        table_name="graph_subscriptions",
        postgresql_where=sa.text("graph_subscription_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_graph_subscriptions_active_folder",
        table_name="graph_subscriptions",
        postgresql_where=sa.text(
            "status IN ('CREATING', 'ACTIVE', 'RENEWAL_REQUIRED', 'REAUTHORIZATION_REQUIRED')"
        ),
    )
    op.drop_index("ix_graph_subscriptions_mailbox_folder", table_name="graph_subscriptions")
    op.drop_table("graph_subscriptions")
    op.drop_index(
        "uq_graph_jobs_active_sync_folder",
        table_name="graph_jobs",
        postgresql_where=sa.text("job_type = 'SYNC_FOLDER' AND status IN ('PENDING', 'RUNNING')"),
    )
    op.drop_index(
        "uq_graph_jobs_active_ingest_email",
        table_name="graph_jobs",
        postgresql_where=sa.text("job_type = 'INGEST_EMAIL' AND status IN ('PENDING', 'RUNNING')"),
    )
    op.drop_index("ix_graph_jobs_mailbox_folder", table_name="graph_jobs")
    op.drop_index("ix_graph_jobs_lease_expires", table_name="graph_jobs")
    op.drop_index("ix_graph_jobs_email", table_name="graph_jobs")
    op.drop_index("ix_graph_jobs_claim", table_name="graph_jobs")
    op.drop_table("graph_jobs")
    op.drop_table("worker_heartbeats")
