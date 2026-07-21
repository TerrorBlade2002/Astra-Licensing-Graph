"""Outbound reply drafts (created/sent by future milestones; recorded here)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import DraftStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.task import LicensingTask


class OutboundDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_drafts"
    __table_args__ = (
        Index("ix_outbound_drafts_task", "task_id"),
        enum_check("status", DraftStatus, "status"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="RESTRICT"), nullable=False
    )
    graph_draft_message_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False)
    subject: Mapped[str | None]
    body_text: Mapped[str | None]
    body_html: Mapped[str | None]
    to_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cc_recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[str | None]
    approved_by: Mapped[str | None]
    graph_web_link: Mapped[str | None]
    approved_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]

    task: Mapped[LicensingTask] = relationship(back_populates="drafts")
