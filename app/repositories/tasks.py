"""Licensing task data access."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.models import Email, LicensingTask
from app.repositories.base import BaseRepository
from app.schemas.email import TaskListFilters


class TaskRepository(BaseRepository):
    def _apply_filters(
        self, stmt: Select[tuple[LicensingTask]], filters: TaskListFilters
    ) -> Select[tuple[LicensingTask]]:
        if filters.status is not None:
            stmt = stmt.where(LicensingTask.status == filters.status)
        if filters.queue is not None:
            stmt = stmt.where(LicensingTask.queue == filters.queue)
        if filters.assigned_to is not None:
            stmt = stmt.where(LicensingTask.assigned_to == filters.assigned_to)
        if filters.due_before is not None:
            stmt = stmt.where(LicensingTask.due_date <= filters.due_before)
        if filters.due_after is not None:
            stmt = stmt.where(LicensingTask.due_date >= filters.due_after)
        if filters.vendor is not None:
            stmt = stmt.where(LicensingTask.vendor == filters.vendor)
        if filters.state is not None:
            # "state" filters by US jurisdiction captured on the linked
            # classification; tasks store jurisdictions via classification only.
            from app.models import Classification

            stmt = stmt.join(
                Classification, LicensingTask.classification_id == Classification.id
            ).where(Classification.states.contains([filters.state]))
        return stmt

    async def list_paginated(
        self, filters: TaskListFilters, *, offset: int, limit: int
    ) -> tuple[list[LicensingTask], int]:
        base = self._apply_filters(select(LicensingTask), filters)
        total = await self.session.scalar(
            base.with_only_columns(func.count(LicensingTask.id)).order_by(None)
        )
        rows = await self.session.scalars(
            base.order_by(LicensingTask.created_at.desc(), LicensingTask.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def get_with_items(self, task_id: uuid.UUID) -> LicensingTask | None:
        stmt = (
            select(LicensingTask)
            .where(LicensingTask.id == task_id)
            .options(selectinload(LicensingTask.requested_items))
        )
        result = await self.session.scalars(stmt)
        return result.first()

    async def get_by_task_key(self, task_key: str) -> LicensingTask | None:
        result = await self.session.scalars(
            select(LicensingTask).where(LicensingTask.task_key == task_key)
        )
        return result.first()

    async def get_email(self, email_id: uuid.UUID) -> Email | None:
        return await self.session.get(Email, email_id)
