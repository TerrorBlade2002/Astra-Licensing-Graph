"""Transactional outbox for future Azure Service Bus publication."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import OutboxStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class OutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
        Index("ix_outbox_events_status_available", "status", "available_at"),
        enum_check("status", OutboxStatus, "status"),
    )

    aggregate_type: Mapped[str] = mapped_column(nullable=False)
    aggregate_id: Mapped[str] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'PENDING'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    published_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
