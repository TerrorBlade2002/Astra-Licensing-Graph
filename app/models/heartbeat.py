"""Worker heartbeat records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(primary_key=True)
    worker_type: Mapped[str] = mapped_column(nullable=False)
    hostname: Mapped[str | None]
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(nullable=False)
    heartbeat_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
