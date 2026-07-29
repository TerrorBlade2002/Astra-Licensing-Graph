"""Licensing task board, assignment, lifecycle, requested items, comments, and events."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import LicensingTask, TaskComment, TaskEvent, TaskRequestedItem
from app.models.mixins import utcnow
from app.schemas.milestone4 import (
    CommentMutation,
    RequestedItemMutation,
    TaskAssignMutation,
    TaskMutation,
    TaskTransitionMutation,
)
from app.tasks.lifecycle import TaskLifecycleService

router = APIRouter(prefix="/licensing-tasks", tags=["licensing tasks"])
Reviewer = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
Manager = Annotated[CurrentActor, Depends(require_role(Role.MANAGER))]


def _task(row: LicensingTask) -> dict[str, object]:
    return {
        "id": str(row.id),
        "title": row.title,
        "queue": row.queue,
        "status": row.status,
        "due_date": row.due_date,
        "assigned_to": row.assigned_to,
        "backup_assigned_to": row.backup_assigned_to,
        "priority": row.priority,
        "vendor": row.vendor,
        "email_type": row.email_type,
        "email_id": str(row.email_id) if row.email_id else None,
        "classification_id": str(row.classification_id) if row.classification_id else None,
        "review_id": str(row.review_id) if row.review_id else None,
        "draft_required": row.draft_required,
        "draft_status": row.draft_status,
        "communication_status": row.communication_status,
        "destination_folder_name": row.destination_folder_name,
        "destination_folder_id": row.destination_folder_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("")
async def list_tasks(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    queue: str | None = None,
    assigned_to: str | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
) -> list[dict[str, object]]:
    stmt = select(LicensingTask)
    if status:
        stmt = stmt.where(LicensingTask.status == status)
    if queue:
        stmt = stmt.where(LicensingTask.queue == queue)
    if assigned_to:
        stmt = stmt.where(LicensingTask.assigned_to == assigned_to)
    if due_before:
        stmt = stmt.where(LicensingTask.due_date <= due_before)
    if due_after:
        stmt = stmt.where(LicensingTask.due_date >= due_after)
    return [
        _task(row)
        for row in await session.scalars(stmt.order_by(LicensingTask.due_date.asc().nulls_last()))
    ]


@router.get("/{task_id}")
async def detail(task_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, object]:
    task = await session.get(LicensingTask, task_id)
    if task is None:
        raise NotFoundError("Task does not exist.")
    items = list(
        await session.scalars(
            select(TaskRequestedItem)
            .where(TaskRequestedItem.task_id == task_id)
            .order_by(TaskRequestedItem.sort_order)
        )
    )
    comments = list(
        await session.scalars(
            select(TaskComment)
            .where(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None))
            .order_by(TaskComment.created_at)
        )
    )
    events = list(
        await session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.occurred_at)
        )
    )
    return _task(task) | {
        "notes": task.notes,
        "requested_items": [
            {
                "id": str(i.id),
                "item_text": i.item_text,
                "category": i.category,
                "required": i.required,
                "evidence_quote": i.evidence_quote,
                "status": i.status,
                "owner": i.owner,
            }
            for i in items
        ],
        "comments": [
            {
                "id": str(c.id),
                "body": c.body,
                "comment_type": c.comment_type,
                "created_at": c.created_at,
            }
            for c in comments
        ],
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "actor_id": e.actor_id,
                "metadata": e.event_metadata,
                "occurred_at": e.occurred_at,
            }
            for e in events
        ],
    }


@router.patch("/{task_id}")
async def patch_task(
    task_id: uuid.UUID, body: TaskMutation, session: SessionDep, actor: Reviewer
) -> dict[str, object]:
    task = await session.get(LicensingTask, task_id)
    if task is None:
        raise NotFoundError("Task does not exist.")
    if body.due_date is not None:
        task.due_date = body.due_date
    if body.priority is not None:
        task.priority = body.priority
    if body.notes is not None:
        task.notes = body.notes
    await session.commit()
    return _task(task)


@router.post("/{task_id}/assign")
async def assign(
    task_id: uuid.UUID, body: TaskAssignMutation, session: SessionDep, actor: Manager
) -> dict[str, object]:
    task = await session.get(LicensingTask, task_id)
    if task is None:
        raise NotFoundError("Task does not exist.")
    task.assigned_to, task.backup_assigned_to = body.assigned_to, body.backup_assigned_to
    session.add(
        TaskEvent(
            task_id=task.id,
            event_type="ASSIGNED",
            actor_id=actor.actor_id,
            event_metadata={"assigned_to": body.assigned_to, "backup": body.backup_assigned_to},
            occurred_at=utcnow(),
        )
    )
    await session.commit()
    return _task(task)


@router.post("/{task_id}/transition")
async def transition(
    task_id: uuid.UUID, body: TaskTransitionMutation, session: SessionDep, actor: Reviewer
) -> dict[str, object]:
    return _task(await TaskLifecycleService(session).transition(task_id, body.status, actor))


@router.get("/{task_id}/events")
async def events(
    task_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.occurred_at)
        )
    )
    return [
        {
            "event_type": r.event_type,
            "from_status": r.from_status,
            "to_status": r.to_status,
            "actor_id": r.actor_id,
            "metadata": r.event_metadata,
            "occurred_at": r.occurred_at,
        }
        for r in rows
    ]


@router.post("/{task_id}/requested-items", status_code=201)
async def add_item(
    task_id: uuid.UUID, body: RequestedItemMutation, session: SessionDep, actor: Reviewer
) -> dict[str, object]:
    count = len(
        list(
            await session.scalars(
                select(TaskRequestedItem.id).where(TaskRequestedItem.task_id == task_id)
            )
        )
    )
    row = TaskRequestedItem(task_id=task_id, sort_order=count, **body.model_dump())
    session.add(row)
    await session.commit()
    return {"id": str(row.id), **body.model_dump()}


@router.patch("/{task_id}/requested-items/{item_id}")
async def patch_item(
    task_id: uuid.UUID,
    item_id: uuid.UUID,
    body: RequestedItemMutation,
    session: SessionDep,
    actor: Reviewer,
) -> dict[str, object]:
    row = await session.get(TaskRequestedItem, item_id)
    if row is None or row.task_id != task_id:
        raise NotFoundError("Requested item does not exist.")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    session.add(
        TaskEvent(
            task_id=task_id,
            event_type="REQUESTED_ITEM_UPDATED",
            actor_id=actor.actor_id,
            event_metadata={"item_id": str(item_id), "status": body.status},
            occurred_at=utcnow(),
        )
    )
    await session.commit()
    return {"id": str(row.id), **body.model_dump()}


@router.delete("/{task_id}/requested-items/{item_id}", status_code=204)
async def delete_item(
    task_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, actor: Reviewer
) -> Response:
    row = await session.get(TaskRequestedItem, item_id)
    if row is None or row.task_id != task_id:
        raise NotFoundError("Requested item does not exist.")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.get("/{task_id}/comments")
async def comments(
    task_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(TaskComment)
            .where(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None))
            .order_by(TaskComment.created_at)
        )
    )
    return [
        {
            "id": str(r.id),
            "body": r.body,
            "comment_type": r.comment_type,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/{task_id}/comments", status_code=201)
async def comment(
    task_id: uuid.UUID, body: CommentMutation, session: SessionDep, actor: Reviewer
) -> dict[str, object]:
    if re.search(r"<\s*(script|iframe|object|embed|style)\b", body.body, re.I):
        raise HTTPException(status_code=400, detail="Executable HTML is not permitted in comments.")
    row = TaskComment(task_id=task_id, body=body.body, comment_type=body.comment_type)
    session.add(row)
    await session.commit()
    return {
        "id": str(row.id),
        "body": row.body,
        "comment_type": row.comment_type,
        "created_at": row.created_at,
    }
