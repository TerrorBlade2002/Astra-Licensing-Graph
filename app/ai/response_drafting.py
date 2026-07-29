"""Strict review-only contract for optional AI response wording suggestions."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field


class ResponseClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2000)


class ResponseSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1, max_length=50_000)
    body_html: str | None = None
    claims_used: list[ResponseClaim]
    warnings: list[str]


class ResponseSuggestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_type: str
    current_subject: str
    current_body_text: str
    reviewed_classification_summary: str | None
    verified_requested_items: list[dict[str, str]]
    approved_document_metadata: list[dict[str, str]]
    tone_guidelines: str


class ResponseSuggestionProvider(ABC):
    @abstractmethod
    async def suggest(
        self, input: ResponseSuggestionInput, correlation_id: uuid.UUID
    ) -> ResponseSuggestion: ...

    async def aclose(self) -> None:
        return None
