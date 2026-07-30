"""Webhook endpoint API tests (no Graph HTTP call may ever occur)."""

from __future__ import annotations

import sys
import time

import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.enums import JobType
from app.models import GraphJob, GraphNotificationReceipt
from tests.conftest import create_inbox_folder, create_mailbox, create_subscription_row
from tests.fixtures.graph_payloads import notification_item

CLIENT_STATE = "synthetic-client-state"
WEBHOOK = "/webhooks/microsoft-graph/messages"


@pytest.fixture
async def seeded_subscription(session: AsyncSession):
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder, client_state=CLIENT_STATE)
    await session.commit()
    return row


async def test_validation_token_is_echoed_exactly_as_plain_text(client: AsyncClient) -> None:
    response = await client.post(f"{WEBHOOK}?validationToken=milestone2-test")
    assert response.status_code == 200
    assert response.text == "milestone2-test"
    assert response.headers["content-type"].startswith("text/plain")


async def test_validation_token_with_url_encoding(client: AsyncClient) -> None:
    response = await client.post(
        WEBHOOK, params={"validationToken": "Token with spaces & symbols =="}
    )
    assert response.status_code == 200
    assert response.text == "Token with spaces & symbols =="


@respx.mock(assert_all_mocked=True)
async def test_valid_notification_persists_receipt_and_enqueues_job(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    # Zero respx routes are registered: any outbound Graph HTTP call would
    # raise immediately, proving the handler never calls Graph.
    #
    # Warm the app first: the measurement below is about the handler's fast
    # path, not about first-request import and connection-pool cost.
    await client.get("/health/ready")
    started = time.perf_counter()
    response = await client.post(
        WEBHOOK,
        json={
            "value": [notification_item(subscription_id="synth-sub-001", client_state=CLIENT_STATE)]
        },
    )
    duration = time.perf_counter() - started
    assert response.status_code == 202
    # The fast path itself is guaranteed structurally by the respx mock above.
    # The wall-clock bound is a supporting check, and only meaningful when the
    # interpreter is not tracing every line for coverage.
    if "coverage" not in sys.modules:
        assert duration < 2.0

    receipt = await session.scalar(select(GraphNotificationReceipt))
    assert receipt is not None
    assert receipt.processing_status == "ACCEPTED"
    assert receipt.client_state_valid is True
    assert receipt.graph_subscription_db_id == seeded_subscription.id

    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert job is not None
    assert job.folder_id == seeded_subscription.folder_id


async def test_duplicate_notification_creates_no_second_job(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    body = {
        "value": [notification_item(subscription_id="synth-sub-001", client_state=CLIENT_STATE)]
    }
    first = await client.post(WEBHOOK, json=body)
    second = await client.post(WEBHOOK, json=body)
    assert first.status_code == second.status_code == 202

    receipts = await session.scalar(select(func.count(GraphNotificationReceipt.id)))
    assert receipts == 1  # duplicate detected by idempotency key
    jobs = await session.scalar(select(func.count(GraphJob.id)))
    assert jobs == 1


async def test_invalid_client_state_creates_receipt_but_no_job(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    response = await client.post(
        WEBHOOK,
        json={
            "value": [
                notification_item(subscription_id="synth-sub-001", client_state="wrong-secret")
            ]
        },
    )
    assert response.status_code == 202  # never reveals whether the sub exists

    receipt = await session.scalar(select(GraphNotificationReceipt))
    assert receipt is not None
    assert receipt.processing_status == "INVALID_CLIENT_STATE"
    assert receipt.client_state_valid is False
    jobs = await session.scalar(select(func.count(GraphJob.id)))
    assert jobs == 0


async def test_unknown_subscription_receipt(client: AsyncClient, session: AsyncSession) -> None:
    response = await client.post(
        WEBHOOK,
        json={"value": [notification_item(subscription_id="never-heard-of-it", client_state="x")]},
    )
    assert response.status_code == 202
    receipt = await session.scalar(select(GraphNotificationReceipt))
    assert receipt is not None
    assert receipt.processing_status == "UNKNOWN_SUBSCRIPTION"
    jobs = await session.scalar(select(func.count(GraphJob.id)))
    assert jobs == 0


async def test_mixed_valid_and_invalid_collection(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    response = await client.post(
        WEBHOOK,
        json={
            "value": [
                notification_item(
                    subscription_id="synth-sub-001",
                    client_state=CLIENT_STATE,
                    notification_id="n-valid",
                ),
                notification_item(
                    subscription_id="synth-sub-001",
                    client_state="wrong",
                    notification_id="n-bad-state",
                ),
                "not-an-object",
                {"noSubscriptionId": True},
            ]
        },
    )
    assert response.status_code == 202
    statuses = (await session.scalars(select(GraphNotificationReceipt.processing_status))).all()
    assert sorted(statuses) == ["ACCEPTED", "INVALID_CLIENT_STATE"]
    jobs = await session.scalar(select(func.count(GraphJob.id)))
    assert jobs == 1


async def test_oversized_body_returns_413(client: AsyncClient, app) -> None:
    limit = app.state.settings.graph_webhook_max_body_bytes
    big = b'{"value": ["' + b"x" * limit + b'"]}'
    response = await client.post(WEBHOOK, content=big, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


async def test_malformed_json_returns_400(client: AsyncClient, session: AsyncSession) -> None:
    response = await client.post(
        WEBHOOK, content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    receipts = await session.scalar(select(func.count(GraphNotificationReceipt.id)))
    assert receipts == 0


async def test_non_collection_json_returns_400(client: AsyncClient) -> None:
    response = await client.post(WEBHOOK, json={"value": "not-a-list"})
    assert response.status_code == 400
