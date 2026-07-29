"""Strict portal contracts for controlled communications."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResponsePlanCreate(BaseModel):
    response_type: str
    recipient_mode: str = "REPLY"
    template_version_id: uuid.UUID | None = None


class ResponsePlanPatch(BaseModel):
    expected_draft_revision: int | None = Field(default=None, ge=1)
    expected_graph_change_key: str | None = None
    expected_graph_etag: str | None = None
    recipient_mode: str | None = None
    reply_all_reviewed: bool | None = None
    bcc_authorized: bool | None = None
    bcc_authorization_reason: str | None = None
    destination_folder_name: str | None = None
    destination_folder_id: str | None = None
    destination_override_reason: str | None = Field(default=None, max_length=1000)


class DraftCreate(BaseModel):
    values: dict[str, Any]


class RecipientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str
    name: str = ""


class DraftMutationExpectation(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_graph_change_key: str | None = None
    expected_graph_etag: str | None = None


class DraftPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_graph_change_key: str | None = None
    expected_graph_etag: str | None = None
    subject: str = Field(min_length=1, max_length=998)
    body_text: str | None = Field(default=None, max_length=50_000)
    body_html: str | None = Field(default=None, max_length=50_000)
    to_recipients: list[RecipientIn]
    cc_recipients: list[RecipientIn] = []
    bcc_recipients: list[RecipientIn] = []
    change_reason: str = Field(min_length=2, max_length=500)


class AttachmentSelect(DraftMutationExpectation):
    document_id: uuid.UUID
    document_version_id: uuid.UUID


class ReviewReason(DraftMutationExpectation):
    reason: str = Field(min_length=2, max_length=1000)


class SendApprovalIn(BaseModel):
    expected_revision: int
    expected_approval_snapshot_sha256: str
    expected_graph_draft_id: str
    expected_graph_change_key: str | None = None
    expected_graph_etag: str | None = None
    approval_notes: str | None = Field(default=None, max_length=1000)


class SendEnqueueIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    explicit_confirmation: bool


class TemplateCreate(BaseModel):
    template_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=200)
    response_type: str
    vendor: str | None = None
    email_type: str | None = None
    jurisdiction: str | None = None


class TemplateVersionCreate(BaseModel):
    subject_template: str | None = None
    text_body_template: str
    html_body_template: str | None = None
    allowed_variables: list[str]


class RecipientPolicyCreate(BaseModel):
    rule_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    rule_type: Literal[
        "BLOCKED_DOMAIN",
        "BLOCKED_ADDRESS",
        "ALLOWED_DOMAIN",
        "ALLOWED_ADDRESS",
        "INTERNAL_ONLY",
        "EXTERNAL_REQUIRES_MANAGER",
        "MAX_RECIPIENTS",
        "BCC_DISABLED",
        "REPLY_ALL_REQUIRES_APPROVAL",
    ]
    priority: int = Field(ge=0, le=100_000)
    conditions: dict[str, Any] = Field(default_factory=dict)
    action: Literal["BLOCK", "WARN"] = "BLOCK"
    reason: str | None = Field(default=None, max_length=1000)
    enabled: bool = True


class RecipientPolicyPatch(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=100_000)
    conditions: dict[str, Any] | None = None
    action: Literal["BLOCK", "WARN"] | None = None
    reason: str = Field(min_length=2, max_length=1000)
    enabled: bool | None = None
