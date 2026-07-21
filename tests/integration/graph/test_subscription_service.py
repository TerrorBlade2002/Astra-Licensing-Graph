"""Subscription lifecycle tests (respx-mocked Graph, real PostgreSQL)."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.enums import GraphSubscriptionStatus
from app.graph.client import GraphHttpClient
from app.graph.subscriptions import GraphSubscriptionApi
from app.models import GraphSubscription
from app.models.mixins import utcnow
from app.services.graph_subscriptions import (
    GraphSubscriptionService,
    SubscriptionConflictError,
)
from app.webhooks.security import hash_client_state
from tests.conftest import create_inbox_folder, create_mailbox, create_subscription_row

BASE = "https://graph.microsoft.com/v1.0"


def _service(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> GraphSubscriptionService:
    return GraphSubscriptionService(session, graph_settings, GraphSubscriptionApi(graph_client))


@respx.mock
async def test_create_subscription_stores_only_hash(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()

    route = respx.post(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(
            201,
            json={"id": "synth-sub-new", "expirationDateTime": "2026-07-27T00:00:00.000Z"},
        )
    )
    service = _service(session, graph_settings, graph_client)
    row = await service.ensure_subscription(mailbox.id, folder.id)

    assert row.status == GraphSubscriptionStatus.ACTIVE.value
    assert row.graph_subscription_id == "synth-sub-new"
    assert row.expiration_at is not None

    sent = json.loads(route.calls.last.request.content)
    client_state = sent["clientState"]
    assert len(client_state) >= 43
    assert sent["latestSupportedTlsVersion"] == "v1_2"
    assert sent["changeType"] == "created,updated,deleted"
    assert "lifecycleNotificationUrl" in sent
    # Only the SHA-256 of the clientState is persisted.
    assert row.client_state_hash == hash_client_state(client_state)
    assert client_state not in row.client_state_hash


@respx.mock
async def test_ensure_is_noop_when_far_from_expiry(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder)
    row.expiration_at = utcnow() + timedelta(days=5)
    await session.commit()

    service = _service(session, graph_settings, graph_client)
    result = await service.ensure_subscription(mailbox.id, folder.id)
    assert result.id == row.id
    assert respx.calls.call_count == 0  # no Graph call at all


@respx.mock
async def test_ensure_renews_inside_renewal_window(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder)
    row.expiration_at = utcnow() + timedelta(hours=2)  # inside 1440-minute window
    await session.commit()

    renew_route = respx.patch(f"{BASE}/subscriptions/synth-sub-001").mock(
        return_value=httpx.Response(
            200, json={"id": "synth-sub-001", "expirationDateTime": "2026-07-30T00:00:00.000Z"}
        )
    )
    service = _service(session, graph_settings, graph_client)
    result = await service.ensure_subscription(mailbox.id, folder.id)
    assert renew_route.called
    assert result.status == GraphSubscriptionStatus.ACTIVE.value
    assert result.last_renewed_at is not None
    assert result.expiration_at is not None and result.expiration_at.year == 2026


@respx.mock
async def test_renew_404_recreates_subscription(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder)
    row.expiration_at = utcnow() + timedelta(hours=1)
    await session.commit()

    respx.patch(f"{BASE}/subscriptions/synth-sub-001").mock(
        return_value=httpx.Response(404, json={"error": {"code": "ResourceNotFound"}})
    )
    respx.post(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(
            201, json={"id": "synth-sub-002", "expirationDateTime": "2026-07-30T00:00:00.000Z"}
        )
    )
    service = _service(session, graph_settings, graph_client)
    result = await service.ensure_subscription(mailbox.id, folder.id)
    assert result.graph_subscription_id == "synth-sub-002"
    assert result.status == GraphSubscriptionStatus.ACTIVE.value

    old = await session.get(GraphSubscription, row.id)
    assert old is not None and old.status == GraphSubscriptionStatus.REMOVED.value


@respx.mock
async def test_removed_subscription_gets_replacement(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(
        session, mailbox, folder, status="REMOVED", graph_subscription_id="synth-old"
    )
    await session.commit()

    respx.post(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(
            201, json={"id": "synth-new", "expirationDateTime": "2026-07-30T00:00:00.000Z"}
        )
    )
    service = _service(session, graph_settings, graph_client)
    result = await service.ensure_subscription(mailbox.id, folder.id)
    assert result.graph_subscription_id == "synth-new"


@respx.mock
async def test_failed_creation_is_compensated(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()

    respx.post(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(400, json={"error": {"code": "InvalidNotificationUrl"}})
    )
    service = _service(session, graph_settings, graph_client)
    with pytest.raises(Exception, match="Graph"):
        await service.ensure_subscription(mailbox.id, folder.id)

    rows = (await session.scalars(select(GraphSubscription))).all()
    assert len(rows) == 1
    assert rows[0].status == GraphSubscriptionStatus.ERROR.value
    assert rows[0].last_error_code == "InvalidNotificationUrl"


async def test_conflicting_active_rows_require_review(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(
        session, mailbox, folder, graph_subscription_id="s1", status="ACTIVE"
    )
    # The partial unique index blocks two ACTIVE rows, so simulate the
    # conflict with an ACTIVE + REAUTHORIZATION_REQUIRED pair created around
    # the index (both are "active" statuses -> index also blocks; instead
    # patch the service query path by inserting ACTIVE + ERROR then flipping).
    other = await create_subscription_row(
        session,
        mailbox,
        folder,
        graph_subscription_id="s2",
        status="ERROR",
        client_state="other-state",
    )
    from sqlalchemy import text

    # Bypass ORM validation to create the conflicting pair the index would
    # normally prevent (simulates historical drift before the index existed).
    await session.execute(text("ALTER TABLE graph_subscriptions DROP CONSTRAINT IF EXISTS _noop"))
    await session.execute(text("DROP INDEX IF EXISTS uq_graph_subscriptions_active_folder"))
    other.status = "RENEWAL_REQUIRED"
    await session.commit()
    try:
        service = _service(session, graph_settings, graph_client)
        with pytest.raises(SubscriptionConflictError):
            await service.ensure_subscription(mailbox.id, folder.id)
    finally:
        await session.rollback()
        # Resolve the synthetic conflict before restoring the guard index.
        await session.execute(
            text(
                "UPDATE graph_subscriptions SET status = 'ERROR' WHERE graph_subscription_id = 's2'"
            )
        )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX uq_graph_subscriptions_active_folder "
                "ON graph_subscriptions (mailbox_id, folder_id) "
                "WHERE status IN ('CREATING', 'ACTIVE', 'RENEWAL_REQUIRED', "
                "'REAUTHORIZATION_REQUIRED')"
            )
        )
        await session.commit()


@respx.mock
async def test_reconcile_adopts_and_reports(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    # Local CREATING row without a Graph ID (creation race remnant).
    orphan = await create_subscription_row(
        session, mailbox, folder, graph_subscription_id=None, status="CREATING"
    )
    await session.commit()

    respx.get(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "remote-match",
                        "resource": orphan.resource,
                        "notificationUrl": graph_settings.notification_url,
                    },
                    {
                        "id": "remote-unknown",
                        "resource": "users/someone-else/mailFolders/x/messages",
                        "notificationUrl": graph_settings.notification_url,
                    },
                ]
            },
        )
    )
    service = _service(session, graph_settings, graph_client)
    report = await service.reconcile(mailbox.id, dry_run=False)
    assert report.adopted == ["remote-match"]
    assert report.remote_only == ["remote-unknown"]
    assert report.deleted_remote == []  # never deleted without the explicit flag
    await session.refresh(orphan)
    assert orphan.graph_subscription_id == "remote-match"
    assert orphan.status == GraphSubscriptionStatus.ACTIVE.value


@respx.mock
async def test_reconcile_marks_local_only_expired(
    session: AsyncSession, graph_settings: Settings, graph_client: GraphHttpClient
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    row = await create_subscription_row(session, mailbox, folder)
    await session.commit()

    respx.get(f"{BASE}/subscriptions").mock(return_value=httpx.Response(200, json={"value": []}))
    service = _service(session, graph_settings, graph_client)
    report = await service.reconcile(mailbox.id, dry_run=False)
    assert report.local_only == [str(row.id)]
    await session.refresh(row)
    assert row.status == GraphSubscriptionStatus.EXPIRED.value
