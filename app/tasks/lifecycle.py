"""Documented licensing task transitions, assignments, and requested-item updates."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.exceptions import NotFoundError, StateConflictError
from app.models import LicensingTask, TaskEvent
from app.models.mixins import utcnow

ALLOWED: dict[str, set[str]] = {
    "OPEN": {"IN_REVIEW", "CANCELLED", "BLOCKED"},
    "IN_REVIEW": {"OPEN", "WAITING_FOR_INFO", "READY_TO_SEND", "CANCELLED", "BLOCKED"},
    "WAITING_FOR_INFO": {"IN_REVIEW", "CANCELLED", "BLOCKED"},
    "READY_TO_SEND": {"IN_REVIEW", "COMPLETED", "CANCELLED", "BLOCKED"},
    "BLOCKED": {"OPEN", "CANCELLED"},
    "OVERDUE": {"OPEN", "IN_REVIEW", "COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


class TaskLifecycleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def transition(
        self, task_id: uuid.UUID, target: str, actor: CurrentActor
    ) -> LicensingTask:
        task = (
            await self.session.scalars(
                select(LicensingTask).where(LicensingTask.id == task_id).with_for_update()
            )
        ).first()
        if task is None:
            raise NotFoundError("Task does not exist.")
        if target not in ALLOWED.get(task.status, set()):
            raise StateConflictError(f"Task transition {task.status} -> {target} is not allowed.")
        previous = task.status
        task.status = target
        if target == "COMPLETED":
            task.completed_at = utcnow()
        self.session.add(
            TaskEvent(
                task_id=task.id,
                event_type="STATUS_CHANGED",
                from_status=previous,
                to_status=target,
                actor_id=actor.actor_id,
                occurred_at=utcnow(),
            )
        )
        await self.session.commit()
        return task
