"""Task API schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ORMModel


class TaskRequestedItemOut(ORMModel):
    id: uuid.UUID
    item_text: str
    status: str
    owner: str | None
    sort_order: int


class TaskSummaryOut(ORMModel):
    id: uuid.UUID
    task_key: str
    title: str
    queue: str
    status: str
    due_date: date | None
    vendor: str | None
    email_type: str | None
    draft_required: bool
    draft_status: str
    assigned_to: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskDetailOut(TaskSummaryOut):
    email_id: uuid.UUID | None
    classification_id: uuid.UUID | None
    review_id: uuid.UUID | None
    destination_folder_name: str | None
    destination_folder_id: str | None
    proposed_action: str | None
    requested_items: list[TaskRequestedItemOut] = Field(default_factory=list)
