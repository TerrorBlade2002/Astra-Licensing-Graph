"""Classification API schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.schemas.common import ORMModel


class ClassificationOut(ORMModel):
    id: uuid.UUID
    email_id: uuid.UUID
    version: int
    schema_version: str
    vendor: str | None
    email_type: str
    states: list[str] = Field(default_factory=list)
    license_types: list[str] = Field(default_factory=list)
    license_numbers: list[str] = Field(default_factory=list)
    requested_information: list[Any] = Field(default_factory=list)
    documents: list[Any] = Field(default_factory=list)
    action_required: bool
    due_date: date | None
    summary: str | None
    proposed_action: str | None
    confidence: Decimal | None
    requires_human_review: bool
    classification_method: str
    rule_matches: list[Any] = Field(default_factory=list)
    model_provider: str | None
    model_name: str | None
    is_current: bool
    created_at: datetime
