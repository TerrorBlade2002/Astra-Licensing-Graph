"""Classification orchestration with no database transaction held over provider I/O."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.base import (
    ClassificationModelInput,
    ClassificationModelProvider,
    ClassificationModelResult,
)
from app.classification.deterministic import (
    AttachmentSignal,
    ClassificationInput,
    DeterministicClassifier,
)
from app.classification.prompt_injection import detect_prompt_injection
from app.classification.schema import ClassificationOutputV1
from app.classification.validation import validate_evidence
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.domain.enums import ActorType, ProcessingState
from app.models import Classification, ClassificationReview, ClassificationRun, Email
from app.models.mixins import utcnow
from app.services.email_state import Actor, _transition_locked


class ClassificationOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: ClassificationModelProvider | None = None,
    ) -> None:
        self.session, self.settings, self.provider = session, settings, provider

    async def classify_email(
        self, email_id: uuid.UUID, *, reclassification: bool = False
    ) -> Classification:
        email = (
            await self.session.scalars(
                select(Email).where(Email.id == email_id).options(selectinload(Email.attachments))
            )
        ).first()
        if email is None:
            raise NotFoundError(f"Email {email_id} does not exist.")
        allowed = {ProcessingState.ATTACHMENTS_SAVED.value}
        if reclassification:
            allowed.add(ProcessingState.CLASSIFIED.value)
        if email.processing_state not in allowed:
            raise StateConflictError("Email is not eligible for classification.")
        payload = ClassificationInput(
            subject=email.subject or "",
            body=email.body_text or email.body_html or "",
            sender_email=email.sender_email,
            attachments=tuple(
                AttachmentSignal(
                    a.original_filename or a.stored_filename or "attachment", a.mime_type
                )
                for a in email.attachments
            ),
            received_date=email.received_at.date() if email.received_at else None,
        )
        deterministic = DeterministicClassifier().classify(payload)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "subject": payload.subject,
                    "body": deterministic.clean_body.current_message,
                    "attachments": [asdict(a) for a in payload.attachments],
                    "schema": "ClassificationOutputV1",
                    "rules": self.settings.classification_rule_set,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        injection = detect_prompt_injection(deterministic.clean_body.current_message)
        model_result: ClassificationModelResult | None = None
        model_error: str | None = None
        # End the read transaction before any external call.
        await self.session.rollback()
        if self.provider is not None and self.settings.ai_classification_enabled:
            try:
                model_result = await self.provider.classify(
                    ClassificationModelInput(
                        subject=payload.subject,
                        sanitized_current_body=deterministic.clean_body.current_message,
                        deterministic_hints=deterministic.output.model_dump(mode="json"),
                        attachments=tuple(
                            {"filename": a.filename, "mime_type": a.mime_type}
                            for a in payload.attachments
                        ),
                    ),
                    "ClassificationOutputV1",
                    "active",
                    uuid.uuid4(),
                )
            except Exception as exc:
                model_error = type(exc).__name__
        output = self._merge(deterministic.output, model_result.output if model_result else None)
        validation_errors = validate_evidence(
            output,
            deterministic.clean_body.current_message,
            {a.filename for a in payload.attachments},
        )
        if validation_errors and model_result:
            output = deterministic.output
        now = utcnow()
        async with self.session.begin():
            locked = (
                await self.session.scalars(
                    select(Email).where(Email.id == email_id).with_for_update()
                )
            ).first()
            if locked is None or locked.processing_state not in allowed:
                raise StateConflictError("Email changed while classification was running.")
            current = (
                await self.session.scalars(
                    select(Classification)
                    .where(Classification.email_id == email_id, Classification.is_current.is_(True))
                    .with_for_update()
                )
            ).first()
            if current:
                current.is_current = False
            run = ClassificationRun(
                email_id=email_id,
                run_type="RECLASSIFICATION"
                if reclassification
                else ("DETERMINISTIC_PLUS_LLM" if model_result else "DETERMINISTIC_ONLY"),
                provider="openai" if model_result else None,
                model=self.settings.openai_model if model_result else None,
                status="SUCCEEDED",
                deterministic_output=deterministic.output.model_dump(mode="json"),
                model_output=model_result.output.model_dump(mode="json") if model_result else None,
                merged_output=output.model_dump(mode="json"),
                validation_errors=validation_errors
                + ([f"model_failure:{model_error}"] if model_error else [])
                + injection,
                input_fingerprint=fingerprint,
                provider_request_id=model_result.provider_request_id if model_result else None,
                input_tokens=model_result.input_tokens if model_result else None,
                output_tokens=model_result.output_tokens if model_result else None,
                total_tokens=model_result.total_tokens if model_result else None,
                latency_ms=model_result.latency_ms if model_result else None,
                started_at=now,
                completed_at=now,
            )
            self.session.add(run)
            await self.session.flush()
            classification = Classification(
                email_id=email_id,
                version=(current.version + 1 if current else 1),
                schema_version="ClassificationOutputV1",
                **self._columns(output),
                classification_method="DETERMINISTIC_PLUS_LLM"
                if model_result
                else "DETERMINISTIC_ONLY",
                rule_matches=[asdict(item) for item in deterministic.evidence],
                model_provider="openai" if model_result else None,
                model_name=self.settings.openai_model if model_result else None,
                model_output=model_result.output.model_dump(mode="json") if model_result else None,
                evidence={
                    "current_message": deterministic.clean_body.current_message,
                    "quoted_history": deterministic.clean_body.quoted_history,
                    "review_reasons": output.review_reasons,
                },
                is_current=True,
                parent_classification_id=current.id if current else None,
                classification_run_id=run.id,
                review_status="PENDING",
                source_revision=(current.source_revision + 1 if current else 1),
            )
            self.session.add(classification)
            await self.session.flush()
            run.classification_id = classification.id
            self.session.add(
                ClassificationReview(classification_id=classification.id, decision="PENDING")
            )
            await _transition_locked(
                self.session,
                email_id,
                ProcessingState.CLASSIFIED,
                Actor(ActorType.SYSTEM, "classification-worker"),
                "Classification stored for mandatory human review.",
                error_code=None,
                error_message=None,
                metadata={
                    "classification_id": str(classification.id),
                    "classification_run_id": str(run.id),
                },
                expected_current_state=ProcessingState(locked.processing_state),
                manual_reset=False,
                event_type="reclassification" if reclassification else "classification",
            )
        return classification

    @staticmethod
    def _merge(
        deterministic: ClassificationOutputV1, model: ClassificationOutputV1 | None
    ) -> ClassificationOutputV1:
        if model is None:
            return deterministic
        data = model.model_dump()
        # Verified deterministic fields win; model fills only gaps and can add conservative context.
        for field in (
            "vendor",
            "email_type",
            "states",
            "license_types",
            "license_numbers",
            "requested_information",
            "documents",
            "due_date",
            "suggested_destination",
        ):
            value = getattr(deterministic, field)
            if value not in (None, [], "", "general_correspondence"):
                data[field] = value
        data["requires_human_review"] = True
        data["confidence"] = min(float(data.get("confidence", 0)), deterministic.confidence + 0.05)
        data["review_reasons"] = list(
            dict.fromkeys(deterministic.review_reasons + model.review_reasons)
        )
        return ClassificationOutputV1.model_validate(data)

    @staticmethod
    def _columns(output: ClassificationOutputV1) -> dict[str, object]:
        data = output.model_dump()
        data.pop("review_reasons")
        return data
