"""Prototype importer integration tests using synthetic fixture trees."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import PrototypeImportError
from app.models import (
    Classification,
    ClassificationReview,
    Email,
    EmailAttachment,
    EmailProcessingEvent,
    EmailRecipient,
    LicensingTask,
    Mailbox,
    MailboxFolder,
    OutboundDraft,
)
from app.services.prototype_import import PrototypeImporter
from tests.fixtures.prototype_builder import MAILBOX, build_prototype_tree


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _run_import(
    session_factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    dry_run: bool = False,
):
    importer = PrototypeImporter(session_factory, root, MAILBOX, dry_run=dry_run)
    return await importer.run()


async def test_normal_single_record_import(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    build_prototype_tree(tmp_path, ["REC001"])
    report = await _run_import(session_factory, tmp_path)
    assert report.inserted == 1 and report.errors == 0

    email = await session.scalar(select(Email))
    assert email is not None
    assert email.graph_message_id == "SYNTH-MSG-REC001"
    assert email.processing_state == "COMPLETED"
    assert email.sender_email == "synthetic.sender@example.invalid"  # normalized lowercase
    assert email.raw_message_storage_uri is not None
    assert email.raw_message_storage_uri.startswith("file:///")

    assert await _count(session, MailboxFolder) == 2
    assert await _count(session, EmailRecipient) == 2  # TO + CC
    assert await _count(session, EmailAttachment) == 1
    attachment = await session.scalar(select(EmailAttachment))
    assert attachment is not None and attachment.sha256_checksum == "AB" * 32

    classification = await session.scalar(select(Classification))
    assert classification is not None
    assert classification.vendor == "RASI" and classification.is_current
    review = await session.scalar(select(ClassificationReview))
    assert review is not None and review.decision == "APPROVED"

    task = await session.scalar(select(LicensingTask))
    assert task is not None
    assert task.task_key == "LIC-REC001"
    assert task.status == "COMPLETED" and task.draft_status == "SENT"

    draft = await session.scalar(select(OutboundDraft))
    assert draft is not None and draft.status == "SENT"


@pytest.mark.parametrize("wrapper", ["single", "array", "nested", "wrapper"])
async def test_wrapper_shapes_import(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    wrapper: str,
) -> None:
    build_prototype_tree(tmp_path, ["RECW"], state_wrapper=wrapper)
    report = await _run_import(session_factory, tmp_path)
    assert report.inserted == 1 and report.errors == 0
    assert await _count(session, Email) == 1


async def test_repeated_import_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    build_prototype_tree(tmp_path, ["RECA", "RECB"])
    first = await _run_import(session_factory, tmp_path)
    assert first.inserted == 2
    second = await _run_import(session_factory, tmp_path)
    assert second.inserted == 0 and second.skipped == 2 and second.errors == 0
    assert await _count(session, Email) == 2
    assert await _count(session, LicensingTask) == 2
    assert await _count(session, MailboxFolder) == 2  # folders not duplicated either


async def test_malformed_record_does_not_corrupt_valid_records(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    build_prototype_tree(tmp_path, ["GOOD1", "BAD1", "GOOD2"], broken_keys={"BAD1"})
    report = await _run_import(session_factory, tmp_path)
    assert report.inserted == 2
    assert report.errors == 1
    failed = [r for r in report.records if r.status == "error"]
    assert failed[0].record_key == "BAD1" and failed[0].reason

    emails = (await session.scalars(select(Email))).all()
    assert {e.graph_message_id for e in emails} == {"SYNTH-MSG-GOOD1", "SYNTH-MSG-GOOD2"}


async def test_completed_workflow_history_is_preserved(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    build_prototype_tree(tmp_path, ["RECH"])
    await _run_import(session_factory, tmp_path)
    events = (
        await session.scalars(
            select(EmailProcessingEvent).order_by(EmailProcessingEvent.occurred_at)
        )
    ).all()
    assert [e.to_state for e in events] == [
        "DISCOVERED",
        "FETCHED",
        "ATTACHMENTS_SAVED",
        "CLASSIFIED",
        "TASK_CREATED",
        "MOVED",
        "COMPLETED",
    ]
    assert events[0].from_state is None
    assert all(e.event_type == "prototype_history" for e in events)
    # Original historical timestamps retained (not re-stamped at import time).
    assert events[0].occurred_at.year == 2026 and events[0].occurred_at.month == 7


async def test_dry_run_creates_no_rows(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    build_prototype_tree(tmp_path, ["RECD"])
    report = await _run_import(session_factory, tmp_path, dry_run=True)
    assert report.dry_run is True
    assert report.inserted == 1  # reports what would be inserted
    for model in (Email, Mailbox, MailboxFolder, LicensingTask, Classification):
        assert await _count(session, model) == 0, model.__name__


async def test_missing_state_file_raises(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    with pytest.raises(PrototypeImportError):
        await _run_import(session_factory, tmp_path / "empty")
