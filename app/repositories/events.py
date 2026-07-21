"""Processing-event and audit-event data access."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select

from app.models import AuditEvent, EmailProcessingEvent
from app.repositories.base import BaseRepository


class EventRepository(BaseRepository):
    async def list_for_email(
        self, email_id: uuid.UUID, *, limit: int | None = None
    ) -> list[EmailProcessingEvent]:
        stmt = (
            select(EmailProcessingEvent)
            .where(EmailProcessingEvent.email_id == email_id)
            .order_by(EmailProcessingEvent.occurred_at.asc(), EmailProcessingEvent.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.scalars(stmt)
        return list(result)

    async def list_audit_events(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        offset: int,
        limit: int,
    ) -> tuple[list[AuditEvent], int]:
        stmt: Select[tuple[AuditEvent]] = select(AuditEvent)
        if entity_type is not None:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)
        if actor_id is not None:
            stmt = stmt.where(AuditEvent.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditEvent.action == action)
        if occurred_from is not None:
            stmt = stmt.where(AuditEvent.occurred_at >= occurred_from)
        if occurred_to is not None:
            stmt = stmt.where(AuditEvent.occurred_at <= occurred_to)
        total = await self.session.scalar(
            stmt.with_only_columns(func.count(AuditEvent.id)).order_by(None)
        )
        rows = await self.session.scalars(
            stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows), int(total or 0)
