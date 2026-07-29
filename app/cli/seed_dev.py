"""CLI: seed development data.

Creates the licensing mailbox, its known folders, and one fully processed
synthetic Colorado RASI record (email -> classification -> review -> task ->
draft -> complete event history). All identifiers are clearly synthetic; no
real Graph IDs or confidential content are used.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import KNOWN_MAILBOX_FOLDERS, LICENSING_MAILBOX_ADDRESS
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.domain.enums import ActorType
from app.models import (
    AuditEvent,
    Classification,
    ClassificationReview,
    Email,
    EmailProcessingEvent,
    EmailRecipient,
    LicensingTask,
    Mailbox,
    MailboxFolder,
    OutboundDraft,
    TaskRequestedItem,
)
from app.services.response_template_service import ResponseTemplateService

SEED_GRAPH_MESSAGE_ID = "SYNTH-GRAPH-MSG-0001"
SEED_TASK_KEY = "LIC-SYNTH-0001"

_HISTORY = (
    (None, "DISCOVERED", "Synthetic message reported by Inbox delta query."),
    ("DISCOVERED", "FETCHED", "Structured message and raw MIME saved."),
    ("FETCHED", "ATTACHMENTS_SAVED", "Attachment inspection completed. 0 attachment(s) found."),
    ("ATTACHMENTS_SAVED", "CLASSIFIED", "Validated classification schema saved."),
    ("CLASSIFIED", "TASK_CREATED", "Review APPROVED; durable task created."),
    ("TASK_CREATED", "MOVED", "Message moved to 08_Info_Required."),
    ("MOVED", "COMPLETED", "Task, draft status, and destination folder committed."),
)


async def seed(session: AsyncSession) -> str:
    existing = await session.scalar(
        select(Email).where(Email.graph_message_id == SEED_GRAPH_MESSAGE_ID)
    )
    if existing is not None:
        return "already-seeded"

    mailbox = await session.scalar(
        select(Mailbox).where(Mailbox.address == LICENSING_MAILBOX_ADDRESS)
    )
    if mailbox is None:
        mailbox = Mailbox(
            id=uuid.uuid4(),
            address=LICENSING_MAILBOX_ADDRESS,
            display_name="Astra Licensing",
            is_active=True,
        )
        session.add(mailbox)
        for index, name in enumerate(KNOWN_MAILBOX_FOLDERS):
            session.add(
                MailboxFolder(
                    mailbox_id=mailbox.id,
                    graph_folder_id=f"SYNTH-FOLDER-{index:03d}",
                    display_name=name,
                    folder_path=name,
                    purpose="Licensing workflow folder",
                )
            )

    base_time = datetime(2026, 7, 20, 20, 0, 0, tzinfo=UTC)
    email = Email(
        id=uuid.uuid4(),
        mailbox_id=mailbox.id,
        graph_message_id=SEED_GRAPH_MESSAGE_ID,
        internet_message_id="<synthetic-0001@example.invalid>",
        conversation_id="SYNTH-CONV-0001",
        subject="Colorado Collection Agency License Renewal - Information Required",
        sender_name="Synthetic Sender",
        sender_email="synthetic.sender@example.invalid",
        received_at=base_time,
        sent_at=base_time - timedelta(minutes=1),
        body_content_type="text",
        body_text=(
            "Synthetic seed record: RASI is preparing the Colorado Collection Agency "
            "License renewal. Please provide the toll-free number, licensing contact, "
            "and call-recording retention period by 2026-07-31."
        ),
        body_preview="Synthetic seed record: RASI is preparing the Colorado...",
        has_attachments=False,
        is_read=True,
        processing_state="COMPLETED",
        discovered_at=base_time + timedelta(minutes=2),
        fetched_at=base_time + timedelta(minutes=3),
        completed_at=base_time + timedelta(hours=21),
    )
    session.add(email)
    session.add(
        EmailRecipient(
            email_id=email.id,
            recipient_type="TO",
            display_name="Astra Licensing",
            address=LICENSING_MAILBOX_ADDRESS,
            ordinal=0,
        )
    )

    classification = Classification(
        id=uuid.uuid4(),
        email_id=email.id,
        version=1,
        schema_version="1.0",
        vendor="RASI",
        email_type="missing_information_request",
        states=["Colorado"],
        license_types=["Collection Agency License"],
        license_numbers=["CO-CA-12345"],
        requested_information=[
            "The current toll-free telephone number",
            "The licensing contact name and email",
            "The call-recording retention period",
        ],
        documents=[],
        action_required=True,
        due_date=date(2026, 7, 31),
        summary="Synthetic: information required for the Colorado license renewal.",
        proposed_action="Provide the requested information by the due date.",
        confidence=0.95,
        requires_human_review=True,
        classification_method="deterministic_rules_plus_llm",
        rule_matches=["information required", "please provide"],
        model_provider=None,
        model_name=None,
        evidence={"subject": email.subject, "synthetic": True},
        is_current=True,
    )
    session.add(classification)

    review = ClassificationReview(
        id=uuid.uuid4(),
        classification_id=classification.id,
        decision="APPROVED",
        reviewer_principal="dev-reviewer@example.invalid",
        reviewed_at=base_time + timedelta(hours=19),
    )
    session.add(review)

    task = LicensingTask(
        id=uuid.uuid4(),
        task_key=SEED_TASK_KEY,
        email_id=email.id,
        classification_id=classification.id,
        review_id=review.id,
        title="Colorado - Collection Agency License - missing information request",
        queue="08_Info_Required",
        status="COMPLETED",
        destination_folder_name="08_Info_Required",
        destination_folder_id="SYNTH-FOLDER-008",
        due_date=date(2026, 7, 31),
        vendor="RASI",
        email_type="missing_information_request",
        proposed_action="Provide the requested information by the due date.",
        draft_required=True,
        draft_status="SENT",
        completed_at=base_time + timedelta(hours=21),
    )
    session.add(task)
    for order, item in enumerate(classification.requested_information):
        session.add(
            TaskRequestedItem(task_id=task.id, item_text=str(item), status="OPEN", sort_order=order)
        )

    session.add(
        OutboundDraft(
            task_id=task.id,
            mailbox_id=mailbox.id,
            graph_draft_message_id="SYNTH-DRAFT-0001",
            status="SENT_COPY_VERIFIED",
            subject="RE: Colorado Collection Agency License Renewal - Information Required",
            body_text="Synthetic draft body.",
            delivery_status="UNKNOWN",
            created_by="dev-reviewer@example.invalid",
            sent_at=base_time + timedelta(hours=20),
        )
    )

    for offset, (from_state, to_state, note) in enumerate(_HISTORY):
        session.add(
            EmailProcessingEvent(
                email_id=email.id,
                from_state=from_state,
                to_state=to_state,
                event_type="seed_history",
                note=note,
                occurred_at=base_time + timedelta(minutes=2 + offset * 10),
            )
        )

    session.add(
        AuditEvent(
            actor_type=ActorType.SYSTEM.value,
            actor_id="seed-dev-cli",
            entity_type="email",
            entity_id=str(email.id),
            action="seed_dev",
            after_data={"graph_message_id": SEED_GRAPH_MESSAGE_ID},
            occurred_at=datetime.now(UTC),
        )
    )
    return "seeded"


async def run() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            outcome = await seed(session)
            await session.commit()
            await ResponseTemplateService(session).ensure_defaults("seed-dev-cli")
    finally:
        await engine.dispose()
    print(outcome)
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
