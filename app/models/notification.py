"""Durable Graph webhook notification receipts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import NotificationReceiptStatus
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_check


class GraphNotificationReceipt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "graph_notification_receipts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_graph_notification_receipts_idem"),
        Index("ix_graph_notification_receipts_sub", "graph_subscription_id", "received_at"),
        Index("ix_graph_notification_receipts_status", "processing_status", "received_at"),
        enum_check("processing_status", NotificationReceiptStatus, "processing_status"),
    )

    graph_subscription_db_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    graph_subscription_id: Mapped[str] = mapped_column(nullable=False)
    graph_notification_id: Mapped[str | None]
    tenant_id: Mapped[str | None]
    change_type: Mapped[str | None]
    lifecycle_event: Mapped[str | None]
    resource: Mapped[str | None]
    payload_hash: Mapped[str] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    client_state_valid: Mapped[bool] = mapped_column(nullable=False)
    processing_status: Mapped[str] = mapped_column(nullable=False)
    correlation_id: Mapped[uuid.UUID | None]
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    receipt_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
