"""Durable licensing tasks and their requested checklist items."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import DraftStatus, RequestedItemStatus, TaskStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check

if TYPE_CHECKING:
    from app.models.classification import Classification
    from app.models.draft import OutboundDraft
    from app.models.email import Email
    from app.models.review import ClassificationReview


class LicensingTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "licensing_tasks"
    __table_args__ = (
        UniqueConstraint("task_key", name="uq_licensing_tasks_task_key"),
        Index("ix_licensing_tasks_status_queue", "status", "queue"),
        Index("ix_licensing_tasks_due_date", "due_date"),
        Index("ix_licensing_tasks_email", "email_id"),
        enum_check("status", TaskStatus, "status"),
        enum_check("draft_status", DraftStatus, "draft_status"),
    )

    task_key: Mapped[str] = mapped_column(nullable=False)
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classifications.id", ondelete="SET NULL"), nullable=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classification_reviews.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(nullable=False)
    queue: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    destination_folder_name: Mapped[str | None]
    destination_folder_id: Mapped[str | None]
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_to: Mapped[str | None]
    backup_assigned_to: Mapped[str | None]
    priority: Mapped[str] = mapped_column(nullable=False, server_default=text("'NORMAL'"))
    notes: Mapped[str | None]
    vendor: Mapped[str | None]
    email_type: Mapped[str | None]
    proposed_action: Mapped[str | None]
    draft_required: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    draft_status: Mapped[str] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    communication_status: Mapped[str] = mapped_column(
        nullable=False, server_default=text("'NOT_STARTED'")
    )

    email: Mapped[Email | None] = relationship(back_populates="tasks")
    classification: Mapped[Classification | None] = relationship()
    review: Mapped[ClassificationReview | None] = relationship()
    requested_items: Mapped[list[TaskRequestedItem]] = relationship(
        back_populates="task", order_by="TaskRequestedItem.sort_order"
    )
    drafts: Mapped[list[OutboundDraft]] = relationship(back_populates="task")


class TaskRequestedItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_requested_items"
    __table_args__ = (
        Index("ix_task_requested_items_task", "task_id"),
        enum_check("status", RequestedItemStatus, "status"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    item_text: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'OPEN'"))
    owner: Mapped[str | None]
    category: Mapped[str | None]
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    evidence_quote: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    task: Mapped[LicensingTask] = relationship(back_populates="requested_items")


class TaskComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_task_created", "task_id", "created_at"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    author_principal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    comment_type: Mapped[str] = mapped_column(nullable=False)
    deleted_at: Mapped[datetime | None]


class TaskEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task_occurred", "task_id", "occurred_at"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("licensing_tasks.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    from_status: Mapped[str | None]
    to_status: Mapped[str | None]
    actor_id: Mapped[str | None]
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
