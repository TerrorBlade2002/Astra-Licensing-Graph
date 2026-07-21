"""Mocked end-to-end flow: webhook -> sync job -> delta -> ingest -> evidence.

Every Graph interaction is respx-mocked; the durable job queue and the real
worker runner drive the pipeline exactly as production would.
"""

from __future__ import annotations

import httpx
import respx
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.jobs.enums import JobStatus, JobType
from app.main import create_app
from app.models import (
    Classification,
    Email,
    EmailAttachment,
    GraphJob,
    GraphNotificationReceipt,
    LicensingTask,
    MailboxSyncState,
    OutboundDraft,
)
from app.workers.context import WorkerContext
from app.workers.runner import QUEUE_JOB_TYPES, WorkerRunner
from tests.conftest import (
    FakeTokenProvider,
    create_inbox_folder,
    create_mailbox,
    create_subscription_row,
)
from tests.fixtures.graph_payloads import (
    delta_link_url,
    delta_message,
    delta_page,
    file_attachment_meta,
    full_message,
    notification_item,
)

BASE = "https://graph.microsoft.com/v1.0"
CLIENT_STATE = "synthetic-client-state"
MSG = "SYNTH-MSG-E2E"
BASELINE_URL = f"{BASE}/users/synth-user/mailFolders/SYNTH-FOLDER-INBOX/messages/delta"
MSG_URL = f"{BASE}/users/synth-user/messages/{MSG}"
MIME_BODY = b"MIME-Version: 1.0\r\n\r\nSynthetic end-to-end MIME."
PDF_BODY = b"%PDF-1.7 synthetic e2e attachment"


def _mock_graph() -> None:
    respx.get(BASELINE_URL).mock(
        return_value=httpx.Response(
            200,
            json=delta_page(
                [delta_message(graph_message_id=MSG, has_attachments=True)],
                delta_link=delta_link_url("e2e-done"),
            ),
        )
    )
    respx.get(f"{MSG_URL}/$value").mock(return_value=httpx.Response(200, content=MIME_BODY))
    respx.get(f"{MSG_URL}/attachments/SYNTH-ATT-001/$value").mock(
        return_value=httpx.Response(200, content=PDF_BODY)
    )
    respx.get(f"{MSG_URL}/attachments").mock(
        return_value=httpx.Response(200, json={"value": [file_attachment_meta(size=len(PDF_BODY))]})
    )
    respx.get(MSG_URL).mock(
        return_value=httpx.Response(
            200, json=full_message(graph_message_id=MSG, has_attachments=True)
        )
    )


@respx.mock
async def test_full_pipeline_from_notification_to_attachments_saved(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    graph_settings: Settings,
    test_database_url: str,
) -> None:
    # 1. An ACTIVE subscription exists.
    mailbox = await create_mailbox(session)
    mailbox.graph_user_id = "synth-user"
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(session, mailbox, folder, client_state=CLIENT_STATE)
    await session.commit()

    _mock_graph()

    # 2-4. Graph posts a change notification; the webhook records a receipt
    # and enqueues a durable SYNC_FOLDER job, returning 202 fast.
    app = create_app(graph_settings)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as web:
            response = await web.post(
                "/webhooks/microsoft-graph/messages",
                json={
                    "value": [
                        notification_item(
                            subscription_id="synth-sub-001", client_state=CLIENT_STATE
                        )
                    ]
                },
            )
            assert response.status_code == 202

    receipt = await session.scalar(select(GraphNotificationReceipt))
    assert receipt is not None and receipt.processing_status == "ACCEPTED"
    sync_job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert sync_job is not None and sync_job.status == JobStatus.PENDING.value

    # 5-12. The real worker drains the queue: delta sync discovers the email,
    # the coalesced ingestion job fetches evidence and attachments.
    ctx = WorkerContext.build(
        graph_settings,
        worker_id="e2e-worker",
        token_provider=FakeTokenProvider(),
    )
    try:
        runner = WorkerRunner(
            ctx,
            job_types=[t for types in QUEUE_JOB_TYPES.values() for t in types],
            poll_interval=0.01,
            once=True,
        )
        processed = await runner.run()
        assert processed >= 2  # sync + ingest
    finally:
        await ctx.aclose()

    # Verify the final state (expire cached rows written by other sessions).
    session.expire_all()
    email = await session.scalar(select(Email))
    assert email is not None
    assert email.graph_message_id == MSG
    assert email.processing_state == "ATTACHMENTS_SAVED"
    assert email.full_message_json_sha256 is not None
    assert email.raw_mime_sha256 is not None

    attachment = await session.scalar(select(EmailAttachment))
    assert attachment is not None
    assert attachment.status == "DOWNLOADED"
    assert attachment.sha256_checksum is not None

    state = await session.scalar(select(MailboxSyncState))
    assert state is not None
    assert state.delta_link == delta_link_url("e2e-done")

    jobs = (await session.scalars(select(GraphJob))).all()
    assert {j.status for j in jobs} == {JobStatus.COMPLETED.value}

    # 13. No classification, task, draft, send, or move occurred.
    assert await session.scalar(select(func.count(Classification.id))) == 0
    assert await session.scalar(select(func.count(LicensingTask.id))) == 0
    assert await session.scalar(select(func.count(OutboundDraft.id))) == 0
    for call in respx.calls:
        assert call.request.method == "GET"
        url = str(call.request.url)
        assert "/sendMail" not in url and "/move" not in url and "/createReply" not in url
