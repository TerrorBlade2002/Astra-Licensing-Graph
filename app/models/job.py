"""Durable PostgreSQL-backed Graph job queue rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.jobs.enums import JobStatus, JobType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, enum_check


class GraphJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "graph_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_graph_jobs_idempotency_key"),
        Index("ix_graph_jobs_claim", "status", "available_at", "priority"),
        Index("ix_graph_jobs_lease_expires", "lease_expires_at"),
        Index("ix_graph_jobs_mailbox_folder", "mailbox_id", "folder_id"),
        Index("ix_graph_jobs_email", "email_id"),
        # Coalescing backstops: one active SYNC_FOLDER per folder and one
        # active INGEST_EMAIL per email.
        Index(
            "uq_graph_jobs_active_sync_folder",
            "folder_id",
            unique=True,
            postgresql_where=text("job_type = 'SYNC_FOLDER' AND status IN ('PENDING', 'RUNNING')"),
        ),
        Index(
            "uq_graph_jobs_active_ingest_email",
            "email_id",
            unique=True,
            postgresql_where=text("job_type = 'INGEST_EMAIL' AND status IN ('PENDING', 'RUNNING')"),
        ),
        enum_check("job_type", JobType, "job_type"),
        enum_check("status", JobStatus, "status"),
    )

    job_type: Mapped[str] = mapped_column(nullable=False)
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=True
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mailbox_folders.id", ondelete="CASCADE"), nullable=True
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=True
    )
    reason: Mapped[str | None]
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
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
