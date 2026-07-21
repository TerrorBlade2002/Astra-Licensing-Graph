"""Append-only processing and audit event tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import ActorType, ProcessingState
from app.models.mixins import UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.email import Email


class EmailProcessingEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "email_processing_events"
    __table_args__ = (
        Index("ix_email_processing_events_email_occurred", "email_id", "occurred_at"),
        Index("ix_email_processing_events_correlation", "correlation_id"),
        enum_check("from_state", ProcessingState, "from_state"),
        enum_check("to_state", ProcessingState, "to_state"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[str | None]
    to_state: Mapped[str] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(nullable=False)
    note: Mapped[str | None]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[uuid.UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)

    email: Mapped[Email] = relationship(back_populates="processing_events")


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_occurred", "occurred_at"),
        Index("ix_audit_events_correlation", "correlation_id"),
        enum_check("actor_type", ActorType, "actor_type"),
    )

    actor_type: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None]
    entity_type: Mapped[str] = mapped_column(nullable=False)
    entity_id: Mapped[str] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[uuid.UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
