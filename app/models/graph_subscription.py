"""Microsoft Graph subscription records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import GraphSubscriptionStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class GraphSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "graph_subscriptions"
    __table_args__ = (
        Index(
            "uq_graph_subscriptions_graph_id",
            "graph_subscription_id",
            unique=True,
            postgresql_where=text("graph_subscription_id IS NOT NULL"),
        ),
        Index("ix_graph_subscriptions_mailbox_folder", "mailbox_id", "folder_id"),
        # At most one active subscription slot per mailbox/folder.
        Index(
            "uq_graph_subscriptions_active_folder",
            "mailbox_id",
            "folder_id",
            unique=True,
            postgresql_where=text(
                "status IN ('CREATING', 'ACTIVE', 'RENEWAL_REQUIRED', 'REAUTHORIZATION_REQUIRED')"
            ),
        ),
        enum_check("status", GraphSubscriptionStatus, "status"),
    )

    mailbox_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False
    )
    folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailbox_folders.id", ondelete="CASCADE"), nullable=False
    )
    graph_subscription_id: Mapped[str | None]
    resource: Mapped[str] = mapped_column(nullable=False)
    change_types: Mapped[str] = mapped_column(nullable=False)
    notification_url: Mapped[str] = mapped_column(nullable=False)
    lifecycle_notification_url: Mapped[str] = mapped_column(nullable=False)
    # SHA-256 of the generated clientState; the plaintext is sent to Graph
    # exactly once at creation time and never persisted.
    client_state_hash: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    expiration_at: Mapped[datetime | None]
    last_renewed_at: Mapped[datetime | None]
    last_notification_at: Mapped[datetime | None]
    last_lifecycle_event_at: Mapped[datetime | None]
    reauthorization_required_at: Mapped[datetime | None]
    removed_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None]
    last_error_message: Mapped[str | None]
