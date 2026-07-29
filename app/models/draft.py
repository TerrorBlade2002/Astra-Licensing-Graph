"""Controlled outbound drafts and exact immutable revisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.communications.enums import (
    CommunicationDraftStatus,
    DeliveryStatus,
    DraftAttachmentStatus,
)
from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.task import LicensingTask


class OutboundDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_drafts"
    __table_args__ = (
        Index("ix_outbound_drafts_task", "task_id"),
        Index("ix_outbound_drafts_status", "draft_status", "updated_at"),
        enum_check("draft_status", CommunicationDraftStatus, "draft_status"),
        enum_check("delivery_status", DeliveryStatus, "delivery_status"),
    )

    response_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("response_plans.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=True
    )
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT"), nullable=False
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "outbound_draft_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_outbound_drafts_current_version",
        ),
        nullable=True,
    )
    graph_draft_message_id: Mapped[str | None]
    graph_change_key: Mapped[str | None]
    graph_etag: Mapped[str | None]
    graph_parent_folder_id: Mapped[str | None]
    graph_web_link: Mapped[str | None]
    subject: Mapped[str] = mapped_column(nullable=False)
    body_text: Mapped[str | None]
    body_html: Mapped[str | None]
    to_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    cc_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    bcc_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    reply_to_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    draft_status: Mapped[str] = mapped_column(nullable=False)
    status = synonym("draft_status")
    local_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    body_sha256: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    recipient_set_sha256: Mapped[str] = mapped_column(nullable=False, default="", server_default="")
    attachment_set_sha256: Mapped[str] = mapped_column(
        nullable=False, default="", server_default=""
    )
    approval_snapshot_sha256: Mapped[str | None]
    created_by_actor: Mapped[str | None]
    created_by: Mapped[str | None]  # retained for imported Milestone 1 history
    approved_by: Mapped[str | None]  # retained for imported Milestone 1 history
    last_edited_by_actor: Mapped[str | None]
    submitted_for_approval_at: Mapped[datetime | None]
    graph_draft_created_at: Mapped[datetime | None]
    graph_last_synced_at: Mapped[datetime | None]
    approved_at: Mapped[datetime | None]
    send_queued_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    delivery_status: Mapped[str] = mapped_column(
        nullable=False, default="NOT_APPLICABLE", server_default="NOT_APPLICABLE"
    )

    task: Mapped[LicensingTask] = relationship(back_populates="drafts")


class OutboundDraftVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "outbound_draft_versions"
    __table_args__ = (
        UniqueConstraint("outbound_draft_id", "revision", name="uq_draft_versions_revision"),
        UniqueConstraint("outbound_draft_id", "snapshot_sha256", name="uq_draft_versions_snapshot"),
    )

    outbound_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(nullable=False)
    body_text: Mapped[str | None]
    body_html: Mapped[str | None]
    to_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cc_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    bcc_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    attachment_manifest: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    body_sha256: Mapped[str] = mapped_column(nullable=False)
    recipient_set_sha256: Mapped[str] = mapped_column(nullable=False)
    attachment_set_sha256: Mapped[str] = mapped_column(nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(nullable=False)
    change_reason: Mapped[str | None]
    created_by_actor: Mapped[str | None]


class OutboundDraftAttachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_draft_attachments"
    __table_args__ = (
        Index("ix_draft_attachments_draft", "outbound_draft_id", "status"),
        enum_check("status", DraftAttachmentStatus, "status"),
    )

    outbound_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_drafts.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT")
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_attachments.id", ondelete="RESTRICT")
    )
    graph_attachment_id: Mapped[str | None]
    filename: Mapped[str] = mapped_column(nullable=False)
    mime_type: Mapped[str | None]
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    upload_method: Mapped[str | None]
    added_by_actor: Mapped[str | None]
    added_at: Mapped[datetime] = mapped_column(nullable=False)
    graph_uploaded_at: Mapped[datetime | None]
    removed_at: Mapped[datetime | None]
