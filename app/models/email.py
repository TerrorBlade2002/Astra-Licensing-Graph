"""Email, recipient, and attachment tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import AttachmentStatus, ProcessingState, RecipientType
from app.models.mixins import (
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)

if TYPE_CHECKING:
    from app.models.classification import Classification
    from app.models.event import EmailProcessingEvent
    from app.models.mailbox import Mailbox
    from app.models.task import LicensingTask


class Email(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "graph_message_id", name="uq_emails_graph_message"),
        Index(
            "uq_emails_internet_message_id",
            "mailbox_id",
            "internet_message_id",
            unique=True,
            postgresql_where=text("internet_message_id IS NOT NULL"),
        ),
        Index("ix_emails_state_received", "mailbox_id", "processing_state", "received_at"),
        Index("ix_emails_conversation_id", "conversation_id"),
        Index(
            "ix_emails_next_retry_at",
            "next_retry_at",
            postgresql_where=text("next_retry_at IS NOT NULL"),
        ),
        enum_check("processing_state", ProcessingState, "processing_state"),
        enum_check("resume_state", ProcessingState, "resume_state"),
    )

    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT"), nullable=False
    )
    graph_message_id: Mapped[str] = mapped_column(nullable=False)
    internet_message_id: Mapped[str | None]
    conversation_id: Mapped[str | None]
    current_graph_folder_id: Mapped[str | None]
    subject: Mapped[str | None]
    sender_name: Mapped[str | None]
    sender_email: Mapped[str | None]
    received_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    body_content_type: Mapped[str | None]
    body_text: Mapped[str | None]
    body_html: Mapped[str | None]
    body_preview: Mapped[str | None]
    has_attachments: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_read: Mapped[bool | None]
    processing_state: Mapped[str] = mapped_column(nullable=False)
    resume_state: Mapped[str | None]
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    raw_message_storage_uri: Mapped[str | None]
    raw_message_sha256: Mapped[str | None]
    source_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    discovered_at: Mapped[datetime | None]
    fetched_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    mailbox: Mapped[Mailbox] = relationship(back_populates="emails")
    recipients: Mapped[list[EmailRecipient]] = relationship(
        back_populates="email", order_by="EmailRecipient.ordinal"
    )
    attachments: Mapped[list[EmailAttachment]] = relationship(back_populates="email")
    classifications: Mapped[list[Classification]] = relationship(back_populates="email")
    tasks: Mapped[list[LicensingTask]] = relationship(back_populates="email")
    processing_events: Mapped[list[EmailProcessingEvent]] = relationship(
        back_populates="email", order_by="EmailProcessingEvent.occurred_at"
    )


class EmailRecipient(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "email_recipients"
    __table_args__ = (
        Index("ix_email_recipients_email_type", "email_id", "recipient_type"),
        enum_check("recipient_type", RecipientType, "recipient_type"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    recipient_type: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str | None]
    address: Mapped[str] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    email: Mapped[Email] = relationship(back_populates="recipients")


class EmailAttachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_attachments"
    __table_args__ = (
        UniqueConstraint("email_id", "graph_attachment_id", name="uq_email_attachments_graph_id"),
        # Duplicate detection: same content (sha256) + same filename on one email.
        Index(
            "uq_email_attachments_dedupe",
            "email_id",
            "sha256_checksum",
            "original_filename",
            unique=True,
            postgresql_where=text("sha256_checksum IS NOT NULL"),
        ),
        enum_check("status", AttachmentStatus, "status"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    graph_attachment_id: Mapped[str] = mapped_column(nullable=False)
    attachment_type: Mapped[str | None]
    original_filename: Mapped[str | None]
    stored_filename: Mapped[str | None]
    mime_type: Mapped[str | None]
    graph_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stored_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_inline: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    content_id: Mapped[str | None]
    storage_uri: Mapped[str | None]
    sha256_checksum: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    downloaded_at: Mapped[datetime | None]

    email: Mapped[Email] = relationship(back_populates="attachments")
