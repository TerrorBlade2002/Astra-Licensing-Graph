"""SharePoint document repository and governed catalog.

Revision ID: 0003_sharepoint_documents
Revises: 0002
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_sharepoint_documents"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "sharepoint_sites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("graph_site_id", sa.Text(), nullable=False),
        sa.Column("hostname", sa.Text()),
        sa.Column("site_path", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("web_url", sa.Text()),
        sa.Column("permission_mode", sa.Text(), nullable=False),
        sa.Column("expected_app_id", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_permission_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("graph_site_id", name="uq_sharepoint_sites_graph_site_id"),
    )
    op.create_table(
        "sharepoint_drives",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Uuid(),
            sa.ForeignKey("sharepoint_sites.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("graph_drive_id", sa.Text(), nullable=False),
        sa.Column("graph_list_id", sa.Text()),
        sa.Column("root_drive_item_id", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("drive_type", sa.Text()),
        sa.Column("web_url", sa.Text()),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("site_id", "graph_drive_id", name="uq_sharepoint_drives_site_graph"),
    )
    op.create_index(
        "uq_sharepoint_drives_active_purpose",
        "sharepoint_drives",
        ["site_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_table(
        "sharepoint_folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "drive_id",
            sa.Uuid(),
            sa.ForeignKey("sharepoint_drives.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("graph_drive_item_id", sa.Text(), nullable=False),
        sa.Column("parent_graph_drive_item_id", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("logical_path", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text()),
        sa.Column("web_url", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("drive_id", "graph_drive_item_id", name="uq_sharepoint_folders_item"),
        sa.UniqueConstraint("drive_id", "logical_path", name="uq_sharepoint_folders_path"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_key", sa.Text(), nullable=False, unique=True),
        sa.Column("current_version_id", sa.Uuid()),
        sa.Column("canonical_title", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text()),
        sa.Column("current_filename", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.Column("approval_status", sa.Text(), nullable=False),
        sa.Column("confidentiality_level", sa.Text(), nullable=False),
        sa.Column("legal_entity", sa.Text()),
        sa.Column("jurisdiction", sa.Text()),
        sa.Column("license_type", sa.Text()),
        sa.Column("license_number", sa.Text()),
        sa.Column("vendor", sa.Text()),
        sa.Column("issue_date", sa.Date()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("renewal_due_date", sa.Date()),
        sa.Column("reusable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "approved_for_reuse", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), sa.ForeignKey("emails.id", ondelete="SET NULL")),
        sa.Column(
            "source_attachment_id",
            sa.Uuid(),
            sa.ForeignKey("email_attachments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_task_id", sa.Uuid(), sa.ForeignKey("licensing_tasks.id", ondelete="SET NULL")
        ),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column("approved_by_actor", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "lifecycle_status IN ('ACTIVE','EXPIRED','SUPERSEDED','ARCHIVED','QUARANTINED','MISSING','DELETED_EXTERNALLY')",
            name="ck_documents_lifecycle_status",
        ),
        sa.CheckConstraint(
            "approval_status IN ('UNREVIEWED','PENDING_REVIEW','APPROVED','REJECTED')",
            name="ck_documents_approval_status",
        ),
        sa.CheckConstraint(
            "confidentiality_level IN ('INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_documents_confidentiality",
        ),
    )
    op.create_index("ix_documents_content_sha256", "documents", ["content_sha256"])
    op.create_index("ix_documents_status_updated", "documents", ["lifecycle_status", "updated_at"])
    op.create_index("ix_documents_expiry_date", "documents", ["expiry_date"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("graph_site_id", sa.Text(), nullable=False),
        sa.Column("graph_drive_id", sa.Text(), nullable=False),
        sa.Column("graph_drive_item_id", sa.Text(), nullable=False),
        sa.Column("graph_list_id", sa.Text()),
        sa.Column("graph_list_item_id", sa.Text()),
        sa.Column("graph_version_id", sa.Text()),
        sa.Column("parent_graph_drive_item_id", sa.Text()),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("web_url", sa.Text()),
        sa.Column("mime_type", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("graph_etag", sa.Text()),
        sa.Column("graph_ctag", sa.Text()),
        sa.Column("storage_status", sa.Text(), nullable=False),
        sa.Column("uploaded_by_actor", sa.Text()),
        sa.Column("upload_job_id", sa.Uuid()),
        sa.Column("source_storage_uri", sa.Text()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        sa.CheckConstraint(
            "storage_status IN ('UPLOADING','AVAILABLE','FAILED','QUARANTINED','MISSING','DELETED_EXTERNALLY')",
            name="ck_document_versions_storage_status",
        ),
    )
    op.create_index("ix_document_versions_hash", "document_versions", ["content_sha256"])
    op.create_index(
        "ix_document_versions_drive_item",
        "document_versions",
        ["graph_drive_id", "graph_drive_item_id"],
    )
    op.create_index(
        "uq_document_versions_graph_version",
        "document_versions",
        ["graph_drive_id", "graph_drive_item_id", "graph_version_id"],
        unique=True,
        postgresql_where=sa.text("graph_version_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "document_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("linked_entity_id", sa.Uuid()),
        sa.Column("linked_external_key", sa.Text()),
        sa.Column("relationship", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_by_actor", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_document_links_exact ON document_links (document_id, link_type, COALESCE(linked_entity_id::text, ''), COALESCE(linked_external_key, ''), relationship)"
    )
    op.create_table(
        "document_metadata_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("before_data", postgresql.JSONB()),
        sa.Column("after_data", postgresql.JSONB()),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text()),
        sa.Column("correlation_id", sa.Uuid()),
        sa.Column("note", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_document_metadata_events_document",
        "document_metadata_events",
        ["document_id", "occurred_at"],
    )
    op.create_table(
        "sharepoint_sync_state",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "drive_id",
            sa.Uuid(),
            sa.ForeignKey("sharepoint_drives.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("delta_link", sa.Text()),
        sa.Column(
            "needs_rebaseline", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_delta_url_fingerprint", sa.Text()),
        sa.Column("last_page_count", sa.Integer()),
        sa.Column("last_change_count", sa.Integer()),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        *_timestamps(),
    )
    op.create_table(
        "document_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE")),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
        ),
        sa.Column("drive_id", sa.Uuid(), sa.ForeignKey("sharepoint_drives.id", ondelete="CASCADE")),
        sa.Column(
            "source_email_attachment_id",
            sa.Uuid(),
            sa.ForeignKey("email_attachments.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("correlation_id", sa.Uuid()),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED_RETRYABLE','FAILED_REVIEW','CANCELLED')",
            name="ck_document_jobs_status",
        ),
    )
    op.create_index(
        "ix_document_jobs_claim", "document_jobs", ["status", "available_at", "priority"]
    )
    op.create_table(
        "sharepoint_upload_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("document_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("encrypted_upload_url", sa.Text()),
        sa.Column("upload_url_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "next_expected_offset", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("sharepoint_upload_sessions")
    op.drop_index("ix_document_jobs_claim", table_name="document_jobs")
    op.drop_table("document_jobs")
    op.drop_table("sharepoint_sync_state")
    op.drop_index("ix_document_metadata_events_document", table_name="document_metadata_events")
    op.drop_table("document_metadata_events")
    op.execute("DROP INDEX IF EXISTS uq_document_links_exact")
    op.drop_table("document_links")
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_index("uq_document_versions_graph_version", table_name="document_versions")
    op.drop_index("ix_document_versions_drive_item", table_name="document_versions")
    op.drop_index("ix_document_versions_hash", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_expiry_date", table_name="documents")
    op.drop_index("ix_documents_status_updated", table_name="documents")
    op.drop_index("ix_documents_content_sha256", table_name="documents")
    op.drop_table("documents")
    op.drop_table("sharepoint_folders")
    op.drop_index("uq_sharepoint_drives_active_purpose", table_name="sharepoint_drives")
    op.drop_table("sharepoint_drives")
    op.drop_table("sharepoint_sites")
