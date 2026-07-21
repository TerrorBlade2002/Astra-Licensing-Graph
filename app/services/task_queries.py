"""Read-side services assembling API responses from repositories."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.emails import EmailRepository
from app.repositories.events import EventRepository
from app.repositories.tasks import TaskRepository
from app.schemas.classification import ClassificationOut
from app.schemas.common import Page, PageParams
from app.schemas.email import (
    EmailBodyOut,
    EmailDetailOut,
    EmailListFilters,
    EmailListItemOut,
    TaskListFilters,
)
from app.schemas.event import EmailProcessingEventOut
from app.schemas.review import ClassificationReviewOut
from app.schemas.task import TaskDetailOut, TaskSummaryOut


async def list_emails(
    session: AsyncSession, filters: EmailListFilters, page: PageParams
) -> Page[EmailListItemOut]:
    repo = EmailRepository(session)
    rows, total = await repo.list_paginated(filters, offset=page.offset, limit=page.page_size)
    return Page(
        items=[EmailListItemOut.model_validate(row) for row in rows],
        page=page.page,
        page_size=page.page_size,
        total=total,
    )


async def get_email_detail(
    session: AsyncSession, email_id: uuid.UUID, *, include_body: bool = False
) -> EmailDetailOut:
    repo = EmailRepository(session)
    email = await repo.get_with_relations(email_id)
    if email is None:
        raise NotFoundError(f"Email {email_id} not found.", details={"email_id": str(email_id)})

    detail = EmailDetailOut.model_validate(email)
    if include_body:
        detail.body = EmailBodyOut.model_validate(email)

    classification = await repo.get_current_classification(email_id)
    if classification is not None:
        detail.current_classification = ClassificationOut.model_validate(classification)

    review = await repo.get_latest_review(email_id)
    if review is not None:
        detail.latest_review = ClassificationReviewOut.model_validate(review)

    task = await repo.get_task(email_id)
    if task is not None:
        detail.task = TaskSummaryOut.model_validate(task)

    events = await EventRepository(session).list_for_email(email_id, limit=50)
    detail.recent_events = [EmailProcessingEventOut.model_validate(e) for e in events]
    return detail


async def list_tasks(
    session: AsyncSession, filters: TaskListFilters, page: PageParams
) -> Page[TaskSummaryOut]:
    repo = TaskRepository(session)
    rows, total = await repo.list_paginated(filters, offset=page.offset, limit=page.page_size)
    return Page(
        items=[TaskSummaryOut.model_validate(row) for row in rows],
        page=page.page,
        page_size=page.page_size,
        total=total,
    )


async def get_task_detail(session: AsyncSession, task_id: uuid.UUID) -> TaskDetailOut:
    repo = TaskRepository(session)
    task = await repo.get_with_items(task_id)
    if task is None:
        raise NotFoundError(f"Task {task_id} not found.", details={"task_id": str(task_id)})
    return TaskDetailOut.model_validate(task)
