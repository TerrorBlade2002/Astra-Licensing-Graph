"""Governed document catalog, versions, links, events, and jobs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.documents.enums import (
    ApprovalStatus,
    ConfidentialityLevel,
    DocumentJobStatus,
    LifecycleStatus,
    StorageStatus,
)
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_content_sha256", "content_sha256"),
        Index("ix_documents_status_updated", "lifecycle_status", "updated_at"),
        Index("ix_documents_expiry_date", "expiry_date"),
        enum_check("lifecycle_status", LifecycleStatus, "ck_documents_lifecycle_status"),
        enum_check("approval_status", ApprovalStatus, "ck_documents_approval_status"),
        enum_check("confidentiality_level", ConfidentialityLevel, "ck_documents_confidentiality"),
    )

    document_key: Mapped[str] = mapped_column(unique=True, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_documents_current_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    canonical_title: Mapped[str] = mapped_column(nullable=False)
    original_filename: Mapped[str | None]
    current_filename: Mapped[str] = mapped_column(nullable=False)
    document_type: Mapped[str] = mapped_column(nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(nullable=False)
    approval_status: Mapped[str] = mapped_column(nullable=False)
    confidentiality_level: Mapped[str] = mapped_column(nullable=False)
    legal_entity: Mapped[str | None]
    jurisdiction: Mapped[str | None]
    license_type: Mapped[str | None]
    license_number: Mapped[str | None]
    vendor: Mapped[str | None]
    issue_date: Mapped[date | None]
    effective_date: Mapped[date | None]
    expiry_date: Mapped[date | None]
    renewal_due_date: Mapped[date | None]
    reusable: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    approved_for_reuse: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    content_sha256: Mapped[str] = mapped_column(nullable=False)
    mime_type: Mapped[str | None]
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(nullable=False)
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL")
    )
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_attachments.id", ondelete="SET NULL")
    )
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="SET NULL")
    )
    created_by_actor: Mapped[str | None]
    approved_by_actor: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    superseded_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]


class DocumentVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        Index("ix_document_versions_hash", "content_sha256"),
        Index("ix_document_versions_drive_item", "graph_drive_id", "graph_drive_item_id"),
        Index(
            "uq_document_versions_graph_version",
            "graph_drive_id",
            "graph_drive_item_id",
            "graph_version_id",
            unique=True,
            postgresql_where=text("graph_version_id IS NOT NULL"),
        ),
        enum_check("storage_status", StorageStatus, "ck_document_versions_storage_status"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_site_id: Mapped[str] = mapped_column(nullable=False)
    graph_drive_id: Mapped[str] = mapped_column(nullable=False)
    graph_drive_item_id: Mapped[str] = mapped_column(nullable=False)
    graph_list_id: Mapped[str | None]
    graph_list_item_id: Mapped[str | None]
    graph_version_id: Mapped[str | None]
    parent_graph_drive_item_id: Mapped[str | None]
    filename: Mapped[str] = mapped_column(nullable=False)
    web_url: Mapped[str | None]
    mime_type: Mapped[str | None]
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(nullable=False)
    graph_etag: Mapped[str | None]
    graph_ctag: Mapped[str | None]
    storage_status: Mapped[str] = mapped_column(nullable=False)
    uploaded_by_actor: Mapped[str | None]
    upload_job_id: Mapped[uuid.UUID | None]
    source_storage_uri: Mapped[str | None]
    uploaded_at: Mapped[datetime] = mapped_column(nullable=False)
    discovered_at: Mapped[datetime | None]


class DocumentLink(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "document_links"
    __table_args__ = (
        Index(
            "uq_document_links_exact",
            "document_id",
            "link_type",
            text("COALESCE(linked_entity_id::text, '')"),
            text("COALESCE(linked_external_key, '')"),
            "relationship",
            unique=True,
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(nullable=False)
    linked_entity_id: Mapped[uuid.UUID | None]
    linked_external_key: Mapped[str | None]
    relationship: Mapped[str] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    link_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by_actor: Mapped[str | None]


class DocumentMetadataEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_metadata_events"
    __table_args__ = (Index("ix_document_metadata_events_document", "document_id", "occurred_at"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_type: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]
    note: Mapped[str | None]
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class DocumentJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_jobs"
    __table_args__ = (
        Index("ix_document_jobs_claim", "status", "available_at", "priority"),
        enum_check("status", DocumentJobStatus, "ck_document_jobs_status"),
    )

    job_type: Mapped[str] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    drive_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sharepoint_drives.id", ondelete="CASCADE")
    )
    source_email_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_attachments.id", ondelete="SET NULL")
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
