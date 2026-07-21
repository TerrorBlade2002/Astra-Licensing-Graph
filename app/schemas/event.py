"""Event API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ORMModel


class EmailProcessingEventOut(ORMModel):
    id: uuid.UUID
    email_id: uuid.UUID
    from_state: str | None
    to_state: str
    event_type: str
    note: str | None
    error_code: str | None
    error_message: str | None
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: uuid.UUID | None
    occurred_at: datetime


class AuditEventOut(ORMModel):
    id: uuid.UUID
    actor_type: str
    actor_id: str | None
    entity_type: str
    entity_id: str
    action: str
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: uuid.UUID | None
    occurred_at: datetime


class SystemVersionOut(ORMModel):
    app_name: str
    app_version: str
    environment: str
    migration_revision: str | None
