"""Mailbox, folder, and delta-sync-state tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.email import Email


class Mailbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mailboxes"
    __table_args__ = (
        # Addresses are normalized to lowercase at the application boundary;
        # the functional unique index also guards against mixed-case writes.
        Index("uq_mailboxes_address_lower", text("lower(address)"), unique=True),
    )

    address: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str | None]
    graph_user_id: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    folders: Mapped[list[MailboxFolder]] = relationship(back_populates="mailbox")
    emails: Mapped[list[Email]] = relationship(back_populates="mailbox")


class MailboxFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mailbox_folders"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "graph_folder_id", name="uq_mailbox_folders_graph_id"),
    )

    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False
    )
    graph_folder_id: Mapped[str] = mapped_column(nullable=False)
    parent_graph_folder_id: Mapped[str | None]
    display_name: Mapped[str] = mapped_column(nullable=False)
    folder_path: Mapped[str | None]
    purpose: Mapped[str | None]
    is_hidden: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    last_verified_at: Mapped[datetime | None]

    mailbox: Mapped[Mailbox] = relationship(back_populates="folders")


class MailboxSyncState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mailbox_sync_state"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "folder_id", name="uq_mailbox_sync_state_folder"),
    )

    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False
    )
    folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailbox_folders.id", ondelete="CASCADE"), nullable=False
    )
    # Opaque Graph delta URL: never exposed via the API, never fully logged.
    delta_link: Mapped[str | None]
    last_started_at: Mapped[datetime | None]
    last_completed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    needs_rebaseline: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    last_delta_url_fingerprint: Mapped[str | None]
    last_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_change_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_successful_job_id: Mapped[uuid.UUID | None]
    last_failed_job_id: Mapped[uuid.UUID | None]
