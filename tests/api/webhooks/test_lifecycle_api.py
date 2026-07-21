"""Lifecycle-notification endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import GraphSubscriptionStatus
from app.jobs.enums import JobType
from app.models import GraphJob, GraphNotificationReceipt, GraphSubscription
from tests.conftest import create_inbox_folder, create_mailbox, create_subscription_row
from tests.fixtures.graph_payloads import notification_item

CLIENT_STATE = "synthetic-client-state"
LIFECYCLE = "/webhooks/microsoft-graph/lifecycle"


@pytest.fixture
async def seeded_subscription(session: AsyncSession):
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder, client_state=CLIENT_STATE)
    await session.commit()
    return row


def _lifecycle_body(event: str, *, client_state: str = CLIENT_STATE, notif_id: str = "lc-1"):
    return {
        "value": [
            notification_item(
                subscription_id="synth-sub-001",
                client_state=client_state,
                lifecycle_event=event,
                notification_id=notif_id,
            )
        ]
    }


async def test_lifecycle_validation_token_echo(client: AsyncClient) -> None:
    response = await client.post(f"{LIFECYCLE}?validationToken=lifecycle-check")
    assert response.status_code == 200 and response.text == "lifecycle-check"


async def test_reauthorization_required(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    sub_id = seeded_subscription.id
    response = await client.post(LIFECYCLE, json=_lifecycle_body("reauthorizationRequired"))
    assert response.status_code == 202

    session.expire_all()  # the webhook wrote through the app's own session
    row = await session.get(GraphSubscription, sub_id)
    assert row is not None
    assert row.status == GraphSubscriptionStatus.REAUTHORIZATION_REQUIRED.value
    assert row.reauthorization_required_at is not None
    assert row.last_lifecycle_event_at is not None

    job_types = (await session.scalars(select(GraphJob.job_type))).all()
    assert JobType.RENEW_SUBSCRIPTION.value in job_types
    assert JobType.SYNC_FOLDER.value in job_types  # reconciliation safeguard


async def test_subscription_removed_schedules_recreation(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    sub_id = seeded_subscription.id
    response = await client.post(LIFECYCLE, json=_lifecycle_body("subscriptionRemoved"))
    assert response.status_code == 202
    session.expire_all()
    row = await session.get(GraphSubscription, sub_id)
    assert row is not None
    assert row.status == GraphSubscriptionStatus.REMOVED.value
    assert row.removed_at is not None
    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.RECREATE_SUBSCRIPTION.value)
    )
    assert job is not None


async def test_missed_schedules_sync_and_preserves_delta_link(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    import uuid as uuid_mod

    from app.models import MailboxSyncState

    state = MailboxSyncState(
        id=uuid_mod.uuid4(),
        mailbox_id=seeded_subscription.mailbox_id,
        folder_id=seeded_subscription.folder_id,
        delta_link="https://graph.microsoft.com/v1.0/users/x/messages/delta?$deltatoken=keep",
    )
    session.add(state)
    await session.commit()

    response = await client.post(LIFECYCLE, json=_lifecycle_body("missed"))
    assert response.status_code == 202
    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert job is not None
    await session.refresh(state)
    assert state.delta_link is not None  # checkpoint untouched by lifecycle handling


async def test_duplicate_lifecycle_notification(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    body = _lifecycle_body("missed", notif_id="lc-dup")
    await client.post(LIFECYCLE, json=body)
    await client.post(LIFECYCLE, json=body)
    receipts = await session.scalar(select(func.count(GraphNotificationReceipt.id)))
    assert receipts == 1
    jobs = await session.scalar(
        select(func.count(GraphJob.id)).where(GraphJob.job_type == JobType.SYNC_FOLDER.value)
    )
    assert jobs == 1


async def test_lifecycle_with_invalid_client_state_is_ignored(
    client: AsyncClient, session: AsyncSession, seeded_subscription
) -> None:
    sub_id = seeded_subscription.id
    response = await client.post(
        LIFECYCLE, json=_lifecycle_body("subscriptionRemoved", client_state="wrong")
    )
    assert response.status_code == 202
    session.expire_all()
    row = await session.get(GraphSubscription, sub_id)
    assert row is not None
    assert row.status == GraphSubscriptionStatus.ACTIVE.value  # untouched
    jobs = await session.scalar(select(func.count(GraphJob.id)))
    assert jobs == 0
