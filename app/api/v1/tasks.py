"""Task endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import SessionDep
from app.schemas.common import Page, PageParams
from app.schemas.email import TaskListFilters
from app.schemas.task import TaskDetailOut, TaskSummaryOut
from app.services import task_queries

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=Page[TaskSummaryOut])
async def list_tasks(
    session: SessionDep,
    status: Annotated[str | None, Query()] = None,
    queue: Annotated[str | None, Query()] = None,
    assigned_to: Annotated[str | None, Query()] = None,
    due_before: Annotated[date | None, Query()] = None,
    due_after: Annotated[date | None, Query()] = None,
    vendor: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[TaskSummaryOut]:
    filters = TaskListFilters(
        status=status,
        queue=queue,
        assigned_to=assigned_to,
        due_before=due_before,
        due_after=due_after,
        vendor=vendor,
        state=state,
    )
    return await task_queries.list_tasks(
        session, filters, PageParams(page=page, page_size=page_size)
    )


@router.get("/{task_id}", response_model=TaskDetailOut)
async def get_task(task_id: uuid.UUID, session: SessionDep) -> TaskDetailOut:
    return await task_queries.get_task_detail(session, task_id)
