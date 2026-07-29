"""Provider-neutral classification model boundary."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.classification.schema import ClassificationOutputV1


@dataclass(frozen=True)
class ClassificationModelInput:
    subject: str
    sanitized_current_body: str
    deterministic_hints: dict[str, object]
    attachments: tuple[dict[str, str | None], ...] = ()
    document_metadata: tuple[dict[str, str | None], ...] = ()


@dataclass(frozen=True)
class ClassificationModelResult:
    output: ClassificationOutputV1
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    raw_metadata: dict[str, object] = field(default_factory=dict)


class ClassificationModelProvider(ABC):
    @abstractmethod
    async def classify(
        self,
        input: ClassificationModelInput,
        schema_version: str,
        prompt_version: str,
        correlation_id: uuid.UUID,
    ) -> ClassificationModelResult: ...
