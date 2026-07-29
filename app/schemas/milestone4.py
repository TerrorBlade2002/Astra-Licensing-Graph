"""Portal authentication, review, task-workflow, and dashboard schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.classification.schema import ClassificationOutputV1


class ActorOut(BaseModel):
    user_id: str
    display_name: str | None
    principal_name: str | None
    roles: list[str]
    capabilities: list[str]


class ReviewMutation(BaseModel):
    expected_revision: int = Field(ge=1)


class ReviewReasonMutation(ReviewMutation):
    reason: str = Field(min_length=3, max_length=1000)


class ReviewCorrectionMutation(ReviewMutation):
    classification: ClassificationOutputV1
    correction_reasons: dict[str, str]
    notes: str | None = None


class TaskCreateMutation(BaseModel):
    destination_override: str | None = None
    override_reason: str | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    classification_id: uuid.UUID
    decision: str
    reviewer_principal: str | None
    claimed_at: datetime | None
    claim_expires_at: datetime | None
    revision: int
    review_notes: str | None
    reviewed_at: datetime | None


class ReviewQueueItem(BaseModel):
    review: ReviewOut
    classification: ClassificationOutputV1
    classification_version: int
    email_id: uuid.UUID
    received_at: datetime | None
    sender: str | None
    subject: str | None
    has_attachments: bool


class ReviewDetail(ReviewQueueItem):
    current_message_body: str
    quoted_history: str
    rule_evidence: list[dict[str, object]]
    previous_versions: list[int]


class TaskMutation(BaseModel):
    due_date: date | None = None
    priority: str | None = None
    notes: str | None = None


class TaskAssignMutation(BaseModel):
    assigned_to: str
    backup_assigned_to: str | None = None


class TaskTransitionMutation(BaseModel):
    status: str
    reason: str | None = None


class RequestedItemMutation(BaseModel):
    item_text: str = Field(min_length=2, max_length=500)
    category: str = "unknown"
    required: bool = True
    evidence_quote: str | None = None
    status: str = "OPEN"
    owner: str | None = None


class CommentMutation(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    comment_type: str = "COMMENT"
