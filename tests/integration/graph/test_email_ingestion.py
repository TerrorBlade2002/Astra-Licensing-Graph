"""Email ingestion tests (respx-mocked Graph, real PostgreSQL, tmp evidence)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.enums import FolderMembership
from app.graph.attachments import GraphAttachmentApi
from app.graph.client import GraphHttpClient
from app.graph.errors import EvidenceLimitExceededError
from app.graph.messages import GraphMessageApi
from app.jobs.enums import JobType
from app.models import Email, EmailAttachment, EmailRecipient, GraphJob
from app.services.email_ingestion import EmailIngestionService
from tests.conftest import create_email, create_inbox_folder, create_mailbox
from tests.fixtures.graph_payloads import (
    file_attachment_meta,
    full_message,
    item_attachment_meta,
    reference_attachment_meta,
)

BASE = "https://graph.microsoft.com/v1.0"
MSG = "SYNTH-MSG-001"
MSG_URL = f"{BASE}/users/synth-user/messages/{MSG}"
MIME_BODY = b"MIME-Version: 1.0\r\nSubject: synthetic\r\n\r\nSynthetic MIME body."


def _service(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> EmailIngestionService:
    return EmailIngestionService(
        session,
        graph_settings,
        GraphMessageApi(graph_client),
        GraphAttachmentApi(graph_client),
        evidence_store,
        worker_id="test-worker",
    )


async def _seed_discovered(session: AsyncSession, *, has_attachments: bool = False):
    mailbox = await create_mailbox(session)
    mailbox.graph_user_id = "synth-user"
    folder = await create_inbox_folder(session, mailbox)
    email = await create_email(
        session,
        mailbox,
        graph_message_id=MSG,
        processing_state="DISCOVERED",
        has_attachments=has_attachments,
        current_graph_folder_id=folder.graph_folder_id,
    )
    await session.commit()
    return mailbox, folder, email


def _mock_message(*, has_attachments: bool = False) -> None:
    respx.get(MSG_URL, params={"$select": "id"}).mock(  # never hit; guard route
        return_value=httpx.Response(500)
    )
    respx.get(f"{MSG_URL}/$value").mock(return_value=httpx.Response(200, content=MIME_BODY))
    respx.get(MSG_URL).mock(
        return_value=httpx.Response(
            200, json=full_message(graph_message_id=MSG, has_attachments=has_attachments)
        )
    )


@respx.mock
async def test_zero_attachment_message_reaches_attachments_saved(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    mailbox, _folder, email = await _seed_discovered(session)
    _mock_message()

    service = _service(session, graph_settings, graph_client, evidence_store)
    outcome = await service.ingest(email.id)
    assert outcome == "completed"

    await session.refresh(email)
    assert email.processing_state == "ATTACHMENTS_SAVED"
    assert email.body_text == "Synthetic body text for evidence."  # text preference
    assert email.full_message_json_storage_uri is not None
    assert email.full_message_json_sha256 is not None
    assert email.raw_mime_storage_uri is not None
    assert email.raw_mime_sha256 is not None
    assert email.evidence_saved_at is not None

    # Recipients replaced from the full message.
    recipients = (
        await session.scalars(select(EmailRecipient).where(EmailRecipient.email_id == email.id))
    ).all()
    assert {r.recipient_type for r in recipients} == {"TO"}
    assert recipients[0].address == "astralicensing@astraglobal.com"

    # Evidence bytes verifiable.
    stored_mime = await evidence_store.open(f"mailboxes/{mailbox.id}/emails/{email.id}/message.eml")
    assert stored_mime == MIME_BODY
    stored_json = json.loads(
        await evidence_store.open(f"mailboxes/{mailbox.id}/emails/{email.id}/message.json")
    )
    assert stored_json["id"] == MSG

    # Attachment rows: none.
    count = await session.scalar(select(func.count(EmailAttachment.id)))
    assert count == 0

    # State history: DISCOVERED -> FETCHED -> ATTACHMENTS_SAVED.
    from app.models import EmailProcessingEvent

    events = (
        await session.scalars(
            select(EmailProcessingEvent).order_by(EmailProcessingEvent.occurred_at)
        )
    ).all()
    assert [e.to_state for e in events] == ["FETCHED", "ATTACHMENTS_SAVED"]


@respx.mock
async def test_file_attachment_downloaded_and_hashed(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    pdf_bytes = b"%PDF-1.7 synthetic"
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    file_attachment_meta(attachment_id="SYNTH-ATT-1", size=len(pdf_bytes)),
                    file_attachment_meta(
                        attachment_id="SYNTH-ATT-2",
                        name="inline.png",
                        content_type="image/png",
                        size=10,
                        is_inline=True,
                    ),
                ]
            },
        )
    )
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-1/$value").mock(
        return_value=httpx.Response(200, content=pdf_bytes)
    )
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-2/$value").mock(
        return_value=httpx.Response(200, content=b"PNG-synthetic")
    )

    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)

    await session.refresh(email)
    assert email.processing_state == "ATTACHMENTS_SAVED"
    rows = (
        await session.scalars(select(EmailAttachment).order_by(EmailAttachment.graph_attachment_id))
    ).all()
    assert len(rows) == 2
    pdf, inline = rows
    assert pdf.status == "DOWNLOADED"
    assert pdf.sha256_checksum is not None
    assert pdf.stored_size_bytes == len(pdf_bytes)
    assert pdf.storage_uri and "attachments" in pdf.storage_uri
    assert inline.is_inline is True  # inline flag retained
    assert inline.status == "DOWNLOADED"


@respx.mock
async def test_item_and_reference_attachments(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(
            200,
            json={"value": [item_attachment_meta(), reference_attachment_meta()]},
        )
    )
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-ITEM").mock(
        return_value=httpx.Response(
            200, json={"id": "SYNTH-ATT-ITEM", "item": {"subject": "Forwarded synthetic"}}
        )
    )

    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)

    rows = {
        r.graph_attachment_id: r for r in (await session.scalars(select(EmailAttachment))).all()
    }
    assert rows["SYNTH-ATT-ITEM"].status == "DOWNLOADED"
    assert rows["SYNTH-ATT-ITEM"].attachment_type == "#microsoft.graph.itemAttachment"
    assert rows["SYNTH-ATT-ITEM"].storage_uri.endswith(".item.json")
    assert rows["SYNTH-ATT-REF"].status == "REFERENCE_NOT_DOWNLOADED"
    assert rows["SYNTH-ATT-REF"].storage_uri is None
    await session.refresh(email)
    assert email.processing_state == "ATTACHMENTS_SAVED"


@respx.mock
async def test_oversized_attachment_is_quarantined(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    huge = graph_settings.max_attachment_bytes + 1
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(200, json={"value": [file_attachment_meta(size=huge)]})
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)
    row = await session.scalar(select(EmailAttachment))
    assert row is not None and row.status == "QUARANTINED"
    assert row.storage_uri is None  # nothing was buffered or stored
    await session.refresh(email)
    assert email.processing_state == "ATTACHMENTS_SAVED"  # quarantine is terminal


@respx.mock
async def test_disallowed_content_type_is_quarantined(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    file_attachment_meta(
                        name="malware.exe", content_type="application/x-msdownload"
                    )
                ]
            },
        )
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)
    row = await session.scalar(select(EmailAttachment))
    assert row is not None and row.status == "QUARANTINED"


@respx.mock
async def test_unsafe_filename_is_sanitized_on_disk(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    file_attachment_meta(
                        name="..\\..\\evil\\..\\traversal.pdf", content_type="application/pdf"
                    )
                ]
            },
        )
    )
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-001/$value").mock(
        return_value=httpx.Response(200, content=b"%PDF-safe")
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)
    row = await session.scalar(select(EmailAttachment))
    assert row is not None
    assert row.original_filename == "..\\..\\evil\\..\\traversal.pdf"  # preserved verbatim
    assert row.stored_filename is not None
    assert "\\" not in row.stored_filename and ".." not in row.stored_filename.split("_", 1)[1]
    assert row.status == "DOWNLOADED"


@respx.mock
async def test_attachment_count_policy_routes_to_failed_review(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    many = [
        file_attachment_meta(attachment_id=f"SYNTH-ATT-{i:03d}")
        for i in range(graph_settings.max_attachments_per_message + 1)
    ]
    respx.get(f"{MSG_URL}/attachments").mock(return_value=httpx.Response(200, json={"value": many}))
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)
    await session.refresh(email)
    assert email.processing_state == "FAILED_REVIEW"
    assert email.last_error_code == "attachment_count_exceeded"


@respx.mock
async def test_mime_over_limit_raises_and_leaves_email_discovered(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session)
    respx.get(f"{MSG_URL}/$value").mock(
        return_value=httpx.Response(200, content=b"x" * (graph_settings.max_raw_mime_bytes + 10))
    )
    respx.get(MSG_URL).mock(
        return_value=httpx.Response(200, json=full_message(graph_message_id=MSG))
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    with pytest.raises(EvidenceLimitExceededError):
        await service.ingest(email.id)
    await session.rollback()
    refreshed = await session.get(Email, email.id)
    assert refreshed is not None and refreshed.processing_state == "DISCOVERED"


@respx.mock
async def test_replay_after_fetch_is_idempotent(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session, has_attachments=True)
    _mock_message(has_attachments=True)
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(200, json={"value": [file_attachment_meta(size=8)]})
    )
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-001/$value").mock(
        return_value=httpx.Response(200, content=b"12345678")
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)

    # Second run: email is terminal for ingestion purposes -> skipped.
    outcome = await service.ingest(email.id)
    assert outcome == "skipped"
    count = await session.scalar(select(func.count(EmailAttachment.id)))
    assert count == 1


@respx.mock
async def test_retry_from_failed_retryable_resumes(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session)
    email.processing_state = "FAILED_RETRYABLE"
    email.resume_state = "DISCOVERED"
    await session.commit()
    _mock_message()

    service = _service(session, graph_settings, graph_client, evidence_store)
    outcome = await service.ingest(email.id)
    assert outcome == "completed"
    refreshed = await session.get(Email, email.id)
    assert refreshed is not None and refreshed.processing_state == "ATTACHMENTS_SAVED"


@respx.mock
async def test_message_404_routes_to_failed_review_and_schedules_sync(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    _mailbox, _folder, email = await _seed_discovered(session)
    respx.get(MSG_URL).mock(
        return_value=httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
    )
    service = _service(session, graph_settings, graph_client, evidence_store)
    outcome = await service.ingest(email.id)
    assert outcome == "message_gone"

    refreshed = await session.get(Email, email.id)
    assert refreshed is not None
    assert refreshed.processing_state == "FAILED_REVIEW"
    assert refreshed.last_error_code == "message_not_retrievable"
    assert refreshed.synced_folder_membership == FolderMembership.UNKNOWN.value

    sync_job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert sync_job is not None and "INGESTION_404" in (sync_job.reason or "")


@respx.mock
async def test_no_classification_or_send_invocation(
    session: AsyncSession,
    graph_settings: Settings,
    graph_client: GraphHttpClient,
    evidence_store,
) -> None:
    """The Graph mock only allows GET; any POST (send) or move would fail."""
    _mailbox, _folder, email = await _seed_discovered(session)
    _mock_message()
    service = _service(session, graph_settings, graph_client, evidence_store)
    await service.ingest(email.id)

    for call in respx.calls:
        assert call.request.method == "GET"
        assert "/sendMail" not in str(call.request.url)
        assert "/move" not in str(call.request.url)
        assert "/createReply" not in str(call.request.url)

    from app.models import Classification, LicensingTask, OutboundDraft

    assert await session.scalar(select(func.count(Classification.id))) == 0
    assert await session.scalar(select(func.count(LicensingTask.id))) == 0
    assert await session.scalar(select(func.count(OutboundDraft.id))) == 0
