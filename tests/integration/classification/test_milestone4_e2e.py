from sqlalchemy import func, select

from app.ai.base import ClassificationModelProvider, ClassificationModelResult
from app.auth.actors import CurrentActor
from app.classification.deterministic import ClassificationInput, DeterministicClassifier
from app.classification.orchestration import ClassificationOrchestrator
from app.domain.enums import ActorType
from app.models import (
    ClassificationFieldCorrection,
    Email,
    LicensingTask,
    OutboundDraft,
    TaskRequestedItem,
)
from app.reviews.service import ReviewService
from app.tasks.creation import TaskCreationService
from tests.conftest import create_email, create_mailbox, make_test_settings


class FakeProvider(ClassificationModelProvider):
    async def classify(self, input, schema_version, prompt_version, correlation_id):
        output = (
            DeterministicClassifier()
            .classify(ClassificationInput(subject=input.subject, body=input.sanitized_current_body))
            .output
        )
        return ClassificationModelResult(
            output=output,
            provider_request_id="mock-response",
            input_tokens=15,
            output_tokens=25,
            total_tokens=40,
            latency_ms=8,
        )


async def test_mocked_end_to_end_classification_review_and_task(session, test_database_url) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(
        session,
        mailbox,
        processing_state="ATTACHMENTS_SAVED",
        sender_email="analyst@rasi.com",
        subject="Colorado Collection Agency License renewal - information required",
        body_text=(
            "Please provide:\n- Current toll-free telephone number\n"
            "The requested information is due by July 31, 2026."
        ),
    )
    await session.commit()
    settings = make_test_settings(
        test_database_url,
        AI_CLASSIFICATION_ENABLED=True,
        AI_EXTERNAL_PROVIDER_APPROVED=True,
        AI_DATA_POLICY_ACKNOWLEDGED=True,
        OPENAI_API_KEY="synthetic",
        OPENAI_MODEL="synthetic-model",
    )
    classification = await ClassificationOrchestrator(
        session, settings, FakeProvider()
    ).classify_email(email.id)
    assert classification.email_type == "missing_information_request"
    assert classification.vendor == "RASI"
    assert classification.states == ["Colorado"]
    from app.models import ClassificationReview

    review = (
        await session.scalars(
            select(ClassificationReview).where(
                ClassificationReview.classification_id == classification.id
            )
        )
    ).one()
    actor = CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id="reviewer-1",
        tenant_id="development",
        object_id="reviewer-1",
        roles=("Licensing.Admin",),
    )
    review = await ReviewService(session, settings).claim(classification.id, actor, 1)
    corrected = (
        DeterministicClassifier()
        .classify(
            ClassificationInput(
                subject=email.subject or "",
                body=email.body_text or "",
                sender_email=email.sender_email,
            )
        )
        .output
    )
    corrected = corrected.model_copy(
        update={
            "requested_information": [
                corrected.requested_information[0].model_copy(
                    update={"item": "Verified current toll-free telephone number"}
                )
            ]
        }
    )
    review = await ReviewService(session, settings).decide(
        classification.id,
        actor,
        review.revision,
        "CORRECTED",
        corrected=corrected,
        correction_reasons={"requested_information": "Clarified verification requirement"},
    )
    task = await TaskCreationService(session).create(review.id, actor)
    assert task.status == "OPEN" and task.queue == "08_Info_Required"
    assert (
        await session.scalar(
            select(func.count())
            .select_from(TaskRequestedItem)
            .where(TaskRequestedItem.task_id == task.id)
        )
        == 1
    )
    assert (
        await session.scalar(select(func.count()).select_from(ClassificationFieldCorrection)) == 1
    )
    assert await session.scalar(select(func.count()).select_from(OutboundDraft)) == 0
    assert (await session.get(Email, email.id)).processing_state == "TASK_CREATED"
    assert await session.scalar(select(func.count()).select_from(LicensingTask)) == 1
