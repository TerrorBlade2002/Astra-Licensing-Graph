"""Delta synchronization tests (respx-mocked Graph, real PostgreSQL)."""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.domain.enums import FolderMembership
from app.graph.client import GraphHttpClient
from app.graph.delta import GraphDeltaApi
from app.graph.errors import GraphApiError
from app.jobs.enums import JobStatus, JobType
from app.models import Email, EmailProcessingEvent, GraphJob, MailboxSyncState
from app.services.graph_sync import FolderDeltaSyncService
from tests.conftest import create_inbox_folder, create_mailbox
from tests.fixtures.graph_payloads import (
    delta_link_url,
    delta_message,
    delta_page,
    delta_removed,
    next_link_url,
)

BASE = "https://graph.microsoft.com/v1.0"
BASELINE_URL = f"{BASE}/users/synth-user/mailFolders/SYNTH-FOLDER-INBOX/messages/delta"


def _service(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> FolderDeltaSyncService:
    api = GraphDeltaApi(
        graph_client,
        page_size=graph_settings.graph_delta_page_size,
        select_fields=graph_settings.graph_delta_select,
    )
    return FolderDeltaSyncService(session, graph_settings, api, worker_id="test-worker")


async def _seed(session: AsyncSession):
    mailbox = await create_mailbox(session)
    mailbox.graph_user_id = "synth-user"
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()
    return mailbox, folder


async def _sync_state(session: AsyncSession, mailbox, folder) -> MailboxSyncState:
    state = await session.scalar(
        select(MailboxSyncState).where(
            MailboxSyncState.mailbox_id == mailbox.id,
            MailboxSyncState.folder_id == folder.id,
        )
    )
    assert state is not None
    return state


@respx.mock
async def test_initial_single_page_baseline(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(
            200,
            json=delta_page(
                [delta_message(graph_message_id="SYNTH-MSG-A")],
                delta_link=delta_link_url("tokenA"),
            ),
        )
    )
    result = await _service(session, graph_settings, graph_client).sync_folder(
        mailbox.id, folder.id
    )
    assert (result.pages, result.created, result.updated) == (1, 1, 0)

    email = await session.scalar(select(Email))
    assert email is not None
    assert email.processing_state == "DISCOVERED"
    assert email.sender_email == "sender@example.invalid"  # normalized
    assert email.synced_folder_membership == FolderMembership.PRESENT.value

    state = await _sync_state(session, mailbox, folder)
    assert state.delta_link == delta_link_url("tokenA")
    assert state.last_page_count == 1 and state.last_change_count == 1
    assert state.lease_owner is None  # released

    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.INGEST_EMAIL.value)
    )
    assert job is not None and job.email_id == email.id


@respx.mock
async def test_multi_page_baseline_follows_next_links(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    page2 = next_link_url("page2")
    # All delta URLs share one path; distinguish routes by query parameters,
    # otherwise the first route would swallow every page request.
    respx.get(BASELINE_URL, params={"$skiptoken": "page2"}).mock(
        return_value=httpx.Response(
            200,
            json=delta_page(
                [delta_message(graph_message_id="SYNTH-MSG-2")],
                delta_link=delta_link_url("done"),
            ),
        )
    )
    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(
            200,
            json=delta_page([delta_message(graph_message_id="SYNTH-MSG-1")], next_link=page2),
        )
    )
    result = await _service(session, graph_settings, graph_client).sync_folder(
        mailbox.id, folder.id
    )
    assert result.pages == 2 and result.created == 2
    count = await session.scalar(select(func.count(Email.id)))
    assert count == 2


@respx.mock
async def test_incremental_zero_change_round_saves_new_checkpoint(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    service = _service(session, graph_settings, graph_client)
    state = await service._get_or_create_state(mailbox.id, folder.id)
    state.delta_link = delta_link_url("old")
    await session.commit()

    respx.get(delta_link_url("old")).mock(
        return_value=httpx.Response(200, json=delta_page([], delta_link=delta_link_url("new")))
    )
    result = await service.sync_folder(mailbox.id, folder.id)
    assert result.changes == 0
    state = await _sync_state(session, mailbox, folder)
    assert state.delta_link == delta_link_url("new")


@respx.mock
async def test_update_does_not_reset_processing_state(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    from tests.conftest import create_email

    mailbox, folder = await _seed(session)
    email = await create_email(
        session, mailbox, graph_message_id="SYNTH-MSG-DONE", processing_state="COMPLETED"
    )
    await session.commit()

    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(
            200,
            json=delta_page(
                [delta_message(graph_message_id="SYNTH-MSG-DONE", is_read=True)],
                delta_link=delta_link_url("x"),
            ),
        )
    )
    result = await _service(session, graph_settings, graph_client).sync_folder(
        mailbox.id, folder.id
    )
    assert result.updated == 1 and result.created == 0
    await session.refresh(email)
    assert email.processing_state == "COMPLETED"  # workflow state preserved
    assert email.is_read is True  # metadata refreshed
    # No ingestion job for an already-processed message.
    job_count = await session.scalar(
        select(func.count(GraphJob.id)).where(GraphJob.job_type == JobType.INGEST_EMAIL.value)
    )
    assert job_count == 0


@respx.mock
async def test_removed_entry_keeps_local_email(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    from tests.conftest import create_email

    mailbox, folder = await _seed(session)
    email = await create_email(
        session,
        mailbox,
        graph_message_id="SYNTH-MSG-GONE",
        processing_state="COMPLETED",
        current_graph_folder_id=folder.graph_folder_id,
    )
    await session.commit()

    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(
            200,
            json=delta_page([delta_removed("SYNTH-MSG-GONE")], delta_link=delta_link_url("x")),
        )
    )
    result = await _service(session, graph_settings, graph_client).sync_folder(
        mailbox.id, folder.id
    )
    assert result.removed == 1
    await session.refresh(email)
    assert email.processing_state == "COMPLETED"  # never reset
    assert email.synced_folder_membership == FolderMembership.REMOVED.value
    assert email.removed_from_synced_folder_at is not None
    assert email.current_graph_folder_id is None
    event = await session.scalar(
        select(EmailProcessingEvent).where(EmailProcessingEvent.event_type == "folder_removed")
    )
    assert event is not None
    assert event.from_state == event.to_state == "COMPLETED"


@respx.mock
async def test_duplicate_page_replay_creates_no_duplicates(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    payload = delta_page(
        [delta_message(graph_message_id="SYNTH-MSG-R")], delta_link=delta_link_url("r")
    )
    respx.get(BASELINE_URL).mock(return_value=httpx.Response(200, json=payload))
    service = _service(session, graph_settings, graph_client)
    await service.sync_folder(mailbox.id, folder.id)

    # Force a rebaseline so the same page is replayed end-to-end.
    state = await _sync_state(session, mailbox, folder)
    state.needs_rebaseline = True
    await session.commit()
    await service.sync_folder(mailbox.id, folder.id)

    email_count = await session.scalar(select(func.count(Email.id)))
    assert email_count == 1
    ingest_jobs = await session.scalar(
        select(func.count(GraphJob.id)).where(
            GraphJob.job_type == JobType.INGEST_EMAIL.value,
            GraphJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
        )
    )
    assert ingest_jobs == 1  # coalesced, not duplicated


@respx.mock
async def test_crash_mid_round_keeps_previous_checkpoint_then_replay_succeeds(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    service = _service(session, graph_settings, graph_client)
    state = await service._get_or_create_state(mailbox.id, folder.id)
    state.delta_link = delta_link_url("checkpoint")
    await session.commit()

    page2 = next_link_url("crash-page2")
    page2_route = respx.get(BASELINE_URL, params={"$skiptoken": "crash-page2"}).mock(
        return_value=httpx.Response(400, json={"error": {"code": "badRequest"}})
    )
    respx.get(BASELINE_URL, params={"$deltatoken": "checkpoint"}).mock(
        return_value=httpx.Response(
            200,
            json=delta_page([delta_message(graph_message_id="SYNTH-MSG-P1")], next_link=page2),
        )
    )
    # Page 2 fails hard (non-retryable) mid-round.
    with pytest.raises(GraphApiError):
        await service.sync_folder(mailbox.id, folder.id)

    state = await _sync_state(session, mailbox, folder)
    assert state.delta_link == delta_link_url("checkpoint")  # never advanced
    assert state.last_error_code is not None
    assert state.lease_owner is None  # lease released on failure
    # Page 1 data was committed and survives.
    assert await session.scalar(select(func.count(Email.id))) == 1

    # Replay: this time the round completes; the replayed page must not duplicate.
    page2_route.mock(
        return_value=httpx.Response(
            200,
            json=delta_page(
                [delta_message(graph_message_id="SYNTH-MSG-P2")],
                delta_link=delta_link_url("advanced"),
            ),
        )
    )
    await service.sync_folder(mailbox.id, folder.id)
    state = await _sync_state(session, mailbox, folder)
    assert state.delta_link == delta_link_url("advanced")
    assert await session.scalar(select(func.count(Email.id))) == 2


@respx.mock
async def test_invalid_delta_token_triggers_safe_rebaseline(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    from tests.conftest import create_email

    mailbox, folder = await _seed(session)
    await create_email(session, mailbox, graph_message_id="SYNTH-KEEP")
    service = _service(session, graph_settings, graph_client)
    state = await service._get_or_create_state(mailbox.id, folder.id)
    state.delta_link = delta_link_url("stale")
    await session.commit()

    respx.get(delta_link_url("stale")).mock(
        return_value=httpx.Response(410, json={"error": {"code": "syncStateNotFound"}})
    )
    result = await service.sync_folder(mailbox.id, folder.id)
    assert result.rebaselined

    state = await _sync_state(session, mailbox, folder)
    assert state.delta_link is None
    assert state.needs_rebaseline is True
    assert state.last_delta_url_fingerprint is not None  # fingerprint retained
    # Existing local data untouched.
    assert await session.scalar(select(func.count(Email.id))) == 1
    # A fresh baseline sync job was scheduled.
    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert job is not None and "REBASELINE" in (job.reason or "")


async def test_hostile_saved_delta_url_is_rejected(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    service = _service(session, graph_settings, graph_client)
    state = await service._get_or_create_state(mailbox.id, folder.id)
    state.delta_link = "https://evil.example.com/v1.0/steal?$deltatoken=x"
    await session.commit()

    from app.graph.errors import DeltaUrlValidationError

    with pytest.raises(DeltaUrlValidationError):
        await service.sync_folder(mailbox.id, folder.id)
    state = await _sync_state(session, mailbox, folder)
    assert state.lease_owner is None


@respx.mock
async def test_missing_links_is_invalid_response(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    from app.graph.errors import GraphResponseInvalidError

    mailbox, folder = await _seed(session)
    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(200, json={"value": []})  # no nextLink/deltaLink
    )
    with pytest.raises(GraphResponseInvalidError):
        await _service(session, graph_settings, graph_client).sync_folder(mailbox.id, folder.id)


@respx.mock
async def test_429_then_success_inside_round(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    respx.get(BASELINE_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=delta_page([], delta_link=delta_link_url("after429"))),
        ]
    )
    result = await _service(session, graph_settings, graph_client).sync_folder(
        mailbox.id, folder.id
    )
    assert result.pages == 1


@respx.mock
async def test_concurrent_sync_lease_conflict(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox, folder = await _seed(session)
    service = _service(session, graph_settings, graph_client)
    state = await service._get_or_create_state(mailbox.id, folder.id)
    # Another worker holds a fresh lease.
    from datetime import timedelta

    from app.models.mixins import utcnow

    state.lease_owner = "other-worker"
    state.lease_expires_at = utcnow() + timedelta(seconds=60)
    await session.commit()

    with pytest.raises(DomainError, match="lease"):
        await service.sync_folder(mailbox.id, folder.id)
