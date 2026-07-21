"""Repository/constraint integration tests against real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Classification,
    EmailAttachment,
    EmailProcessingEvent,
    LicensingTask,
    MailboxFolder,
    OutboxEvent,
)
from app.repositories.emails import EmailRepository
from app.repositories.events import EventRepository
from app.repositories.mailboxes import MailboxRepository
from app.schemas.email import EmailListFilters
from tests.conftest import create_email, create_mailbox

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


async def test_mailbox_create_read_normalizes_address(session: AsyncSession) -> None:
    repo = MailboxRepository(session)
    created = await repo.create(address="  MIXED@Example.COM ")
    assert created.address == "mixed@example.com"
    fetched = await repo.get_by_address("Mixed@example.com")
    assert fetched is not None and fetched.id == created.id


async def test_mailbox_address_unique_case_insensitive(session: AsyncSession) -> None:
    repo = MailboxRepository(session)
    await repo.create(address="dup@example.com")
    await session.commit()
    # Bypass the application-boundary lowercase to prove the DB index guards it.
    from app.models import Mailbox

    session.add(Mailbox(address="DUP@example.com"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_folder_uniqueness_per_mailbox(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    session.add(
        MailboxFolder(mailbox_id=mailbox.id, graph_folder_id="F1", display_name="08_Info_Required")
    )
    await session.flush()
    # Same display name under a different Graph ID is allowed.
    session.add(
        MailboxFolder(mailbox_id=mailbox.id, graph_folder_id="F2", display_name="08_Info_Required")
    )
    await session.flush()
    session.add(MailboxFolder(mailbox_id=mailbox.id, graph_folder_id="F1", display_name="Other"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_email_graph_id_unique_per_mailbox(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    await create_email(session, mailbox, graph_message_id="G1")
    with pytest.raises(IntegrityError):
        await create_email(session, mailbox, graph_message_id="G1")
    await session.rollback()


async def test_internet_message_id_partial_unique(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    await create_email(session, mailbox, internet_message_id="<a@x>")
    # NULL internet_message_id rows never collide.
    await create_email(session, mailbox, internet_message_id=None)
    await create_email(session, mailbox, internet_message_id=None)
    with pytest.raises(IntegrityError):
        await create_email(session, mailbox, internet_message_id="<a@x>")
    await session.rollback()


async def test_classification_current_version_partial_unique(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox)

    def make(version: int, is_current: bool) -> Classification:
        return Classification(
            id=uuid.uuid4(),
            email_id=email.id,
            version=version,
            schema_version="1.0",
            email_type="renewal_notice",
            action_required=False,
            requires_human_review=True,
            classification_method="deterministic_rules",
            evidence={},
            is_current=is_current,
        )

    session.add(make(1, is_current=False))
    session.add(make(2, is_current=True))
    await session.flush()
    session.add(make(3, is_current=True))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_classification_version_unique(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox)
    for is_current, version in ((False, 1), (True, 1)):
        session.add(
            Classification(
                id=uuid.uuid4(),
                email_id=email.id,
                version=version,
                schema_version="1.0",
                email_type="renewal_notice",
                action_required=False,
                requires_human_review=True,
                classification_method="rules",
                evidence={},
                is_current=is_current,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_task_key_unique(session: AsyncSession) -> None:
    for _ in range(2):
        session.add(
            LicensingTask(
                id=uuid.uuid4(),
                task_key="LIC-DUP",
                title="t",
                queue="q",
                status="OPEN",
                draft_status="NOT_REQUIRED",
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_attachment_dedupe_index(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox)

    def make(graph_id: str, sha: str | None) -> EmailAttachment:
        return EmailAttachment(
            id=uuid.uuid4(),
            email_id=email.id,
            graph_attachment_id=graph_id,
            original_filename="doc.pdf",
            sha256_checksum=sha,
            status="DOWNLOADED",
        )

    session.add(make("A1", "aaa"))
    session.add(make("A2", None))  # no checksum -> not part of the partial index
    session.add(make("A3", None))
    await session.flush()
    session.add(make("A4", "aaa"))  # same content + same filename -> duplicate
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_event_ordering(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox)
    times = [NOW.replace(minute=m) for m in (30, 10, 20)]
    for t, state in zip(times, ("CLASSIFIED", "DISCOVERED", "FETCHED"), strict=True):
        session.add(
            EmailProcessingEvent(
                email_id=email.id,
                to_state=state,
                event_type="test",
                occurred_at=t,
            )
        )
    await session.flush()
    events = await EventRepository(session).list_for_email(email.id)
    assert [e.to_state for e in events] == ["DISCOVERED", "FETCHED", "CLASSIFIED"]


async def test_outbox_idempotency_key_unique(session: AsyncSession) -> None:
    for _ in range(2):
        session.add(
            OutboxEvent(
                id=uuid.uuid4(),
                aggregate_type="email",
                aggregate_id="x",
                event_type="email.completed",
                payload={},
                idempotency_key="same-key",
                status="PENDING",
                available_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_email_list_filters_and_pagination(session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    for i in range(5):
        await create_email(
            session,
            mailbox,
            subject=f"Renewal {i}",
            received_at=NOW.replace(hour=i + 1),
            processing_state="COMPLETED" if i % 2 == 0 else "DISCOVERED",
        )
    await session.commit()

    repo = EmailRepository(session)
    rows, total = await repo.list_paginated(
        EmailListFilters(processing_state="COMPLETED"), offset=0, limit=2
    )
    assert total == 3
    assert len(rows) == 2
    # Newest first.
    assert rows[0].received_at >= rows[1].received_at

    rows, total = await repo.list_paginated(
        EmailListFilters(subject_contains="renewal 3"), offset=0, limit=10
    )
    assert total == 1 and rows[0].subject == "Renewal 3"
