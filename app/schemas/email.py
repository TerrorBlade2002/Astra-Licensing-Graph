"""Email API schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.classification import ClassificationOut
from app.schemas.common import ORMModel
from app.schemas.event import EmailProcessingEventOut
from app.schemas.review import ClassificationReviewOut
from app.schemas.task import TaskSummaryOut


class EmailRecipientOut(ORMModel):
    id: uuid.UUID
    recipient_type: str
    display_name: str | None
    address: str
    ordinal: int


class EmailAttachmentOut(ORMModel):
    id: uuid.UUID
    graph_attachment_id: str
    attachment_type: str | None
    original_filename: str | None
    stored_filename: str | None
    mime_type: str | None
    graph_size_bytes: int | None
    stored_size_bytes: int | None
    is_inline: bool
    content_id: str | None
    storage_uri: str | None
    sha256_checksum: str | None
    status: str
    downloaded_at: datetime | None


class EmailListItemOut(ORMModel):
    """List representation: metadata only, never body content or raw payloads."""

    id: uuid.UUID
    mailbox_id: uuid.UUID
    graph_message_id: str
    internet_message_id: str | None
    conversation_id: str | None
    subject: str | None
    sender_name: str | None
    sender_email: str | None
    received_at: datetime | None
    has_attachments: bool
    processing_state: str
    resume_state: str | None
    retry_count: int
    last_error_code: str | None
    discovered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmailBodyOut(ORMModel):
    body_content_type: str | None
    body_text: str | None
    body_html: str | None


class EmailDetailOut(EmailListItemOut):
    current_graph_folder_id: str | None
    sent_at: datetime | None
    body_preview: str | None
    is_read: bool | None
    next_retry_at: datetime | None
    last_error_message: str | None
    raw_message_storage_uri: str | None
    raw_message_sha256: str | None
    fetched_at: datetime | None

    body: EmailBodyOut | None = None
    recipients: list[EmailRecipientOut] = Field(default_factory=list)
    attachments: list[EmailAttachmentOut] = Field(default_factory=list)
    current_classification: ClassificationOut | None = None
    latest_review: ClassificationReviewOut | None = None
    task: TaskSummaryOut | None = None
    recent_events: list[EmailProcessingEventOut] = Field(default_factory=list)


class EmailListFilters(BaseModel):
    mailbox_id: uuid.UUID | None = None
    processing_state: str | None = None
    sender_email: str | None = None
    received_from: datetime | None = None
    received_to: datetime | None = None
    has_attachments: bool | None = None
    subject_contains: str | None = None

    @field_validator("sender_email")
    @classmethod
    def _normalize_sender(cls, value: str | None) -> str | None:
        return value.lower().strip() if value else value


class TaskListFilters(BaseModel):
    status: str | None = None
    queue: str | None = None
    assigned_to: str | None = None
    due_before: date | None = None
    due_after: date | None = None
    vendor: str | None = None
    state: str | None = None
