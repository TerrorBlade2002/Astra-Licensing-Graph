"""Pydantic API contracts for the governed document catalog."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_key: str
    current_version_id: uuid.UUID | None
    canonical_title: str
    original_filename: str | None
    current_filename: str
    document_type: str
    lifecycle_status: str
    approval_status: str
    confidentiality_level: str
    legal_entity: str | None
    jurisdiction: str | None
    license_type: str | None
    license_number: str | None
    vendor: str | None
    issue_date: date | None
    effective_date: date | None
    expiry_date: date | None
    renewal_due_date: date | None
    reusable: bool
    approved_for_reuse: bool
    content_sha256: str
    mime_type: str | None
    size_bytes: int
    source_type: str
    source_email_id: uuid.UUID | None
    source_attachment_id: uuid.UUID | None
    source_task_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    graph_drive_id: str
    graph_drive_item_id: str
    graph_version_id: str | None
    filename: str
    web_url: str | None
    mime_type: str | None
    size_bytes: int
    content_sha256: str
    graph_etag: str | None
    graph_ctag: str | None
    storage_status: str
    uploaded_at: datetime


class DocumentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    link_type: str
    linked_entity_id: uuid.UUID | None
    linked_external_key: str | None
    relationship: str
    is_primary: bool
    link_metadata: dict[str, Any]
    created_at: datetime


class DocumentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    actor_type: str
    actor_id: str | None
    note: str | None
    occurred_at: datetime


class DocumentDetailOut(BaseModel):
    document: DocumentOut
    current_version: DocumentVersionOut | None
    versions: list[DocumentVersionOut]
    links: list[DocumentLinkOut]
    recent_events: list[DocumentEventOut]


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    page: int
    page_size: int
    total: int


class DocumentPatch(BaseModel):
    expected_updated_at: datetime
    canonical_title: str | None = None
    document_type: str | None = None
    confidentiality_level: str | None = None
    legal_entity: str | None = None
    jurisdiction: str | None = None
    license_type: str | None = None
    license_number: str | None = None
    vendor: str | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    renewal_due_date: date | None = None
    reusable: bool | None = None


class DocumentLinkCreate(BaseModel):
    link_type: str
    linked_entity_id: uuid.UUID | None = None
    linked_external_key: str | None = Field(default=None, max_length=500)
    relationship: str = Field(min_length=1, max_length=100)
    is_primary: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewedDocumentMetadata(BaseModel):
    canonical_title: str = Field(min_length=1, max_length=500)
    document_type: str = Field(min_length=1, max_length=100)
    legal_entity: str | None = Field(default=None, max_length=200)
    jurisdiction: str | None = Field(default=None, max_length=100)
    license_type: str | None = Field(default=None, max_length=200)
    license_number: str | None = Field(default=None, max_length=200)
    vendor: str | None = Field(default=None, max_length=200)
    issue_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    renewal_due_date: date | None = None
    confidentiality_level: str = "INTERNAL"
    reusable: bool = False


class PromoteAttachmentRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    metadata: ReviewedDocumentMetadata
