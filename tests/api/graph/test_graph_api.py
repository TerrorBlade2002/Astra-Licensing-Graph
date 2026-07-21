"""Operational Graph API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.graph_jobs import _require_mutations_enabled
from app.jobs.enums import JobType
from app.models import AuditEvent, GraphJob
from tests.conftest import (
    create_email,
    create_inbox_folder,
    create_mailbox,
    create_subscription_row,
)


async def test_status_endpoint_reports_counts_without_secrets(
    client: AsyncClient, session: AsyncSession
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(session, mailbox, folder)
    await session.commit()

    response = await client.get("/api/v1/integrations/graph/status")
    assert response.status_code == 200
    body = response.json()
    assert body["graph_enabled"] is False  # default test settings
    assert body["credential_mode"] == "client_secret"
    assert body["mailbox_count"] == 1
    assert body["active_subscriptions"] == 1
    assert body["pending_graph_jobs"] == 0
    text = response.text.lower()
    assert "client_secret_value" not in text
    assert "deltatoken" not in text


async def test_subscription_listing_is_sanitized(
    client: AsyncClient, session: AsyncSession
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(session, mailbox, folder)
    await session.commit()

    response = await client.get("/api/v1/integrations/graph/subscriptions")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    item = items[0]
    assert item["graph_subscription_id"] == "synth-sub-001"
    # Sensitive fields must not be exposed.
    assert "client_state_hash" not in item
    assert "notification_url" not in item
    assert "resource" not in item


async def test_job_listing_filters(client: AsyncClient, session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    email = await create_email(session, mailbox)
    session.add(
        GraphJob(
            id=uuid.uuid4(),
            job_type=JobType.SYNC_FOLDER.value,
            mailbox_id=mailbox.id,
            folder_id=folder.id,
            status="PENDING",
            idempotency_key="job-a",
            max_attempts=3,
            available_at=email.created_at,
        )
    )
    session.add(
        GraphJob(
            id=uuid.uuid4(),
            job_type=JobType.INGEST_EMAIL.value,
            mailbox_id=mailbox.id,
            email_id=email.id,
            status="COMPLETED",
            idempotency_key="job-b",
            max_attempts=3,
            available_at=email.created_at,
        )
    )
    await session.commit()

    all_jobs = await client.get("/api/v1/integrations/graph/jobs")
    assert all_jobs.json()["total"] == 2
    filtered = await client.get(
        "/api/v1/integrations/graph/jobs",
        params={"job_type": "SYNC_FOLDER", "status": "PENDING"},
    )
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["job_type"] == "SYNC_FOLDER"

    by_email = await client.get(
        "/api/v1/integrations/graph/jobs", params={"email_id": str(email.id)}
    )
    assert by_email.json()["total"] == 1


async def test_folder_sync_enqueue_endpoint(client: AsyncClient, session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()

    response = await client.post(f"/api/v1/integrations/graph/folders/{folder.id}/sync")
    assert response.status_code == 202
    body = response.json()
    assert body["created"] is True

    # Repeat coalesces onto the same active job.
    again = await client.post(f"/api/v1/integrations/graph/folders/{folder.id}/sync")
    assert again.json()["job_id"] == body["job_id"]

    audit = await session.scalar(
        select(AuditEvent).where(AuditEvent.action == "sync_enqueued_via_api")
    )
    assert audit is not None


async def test_email_ingest_enqueue_requires_idempotency_key(
    client: AsyncClient, session: AsyncSession
) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox)
    await session.commit()

    missing = await client.post(f"/api/v1/integrations/graph/emails/{email.id}/ingest")
    assert missing.status_code == 422  # Idempotency-Key header required

    ok = await client.post(
        f"/api/v1/integrations/graph/emails/{email.id}/ingest",
        headers={"Idempotency-Key": "manual-test-0001"},
    )
    assert ok.status_code == 202
    repeat = await client.post(
        f"/api/v1/integrations/graph/emails/{email.id}/ingest",
        headers={"Idempotency-Key": "manual-test-0001"},
    )
    assert repeat.json()["job_id"] == ok.json()["job_id"]


async def test_ensure_subscriptions_endpoint(client: AsyncClient, session: AsyncSession) -> None:
    mailbox = await create_mailbox(session)
    await create_inbox_folder(session, mailbox)
    await session.commit()
    response = await client.post(
        f"/api/v1/integrations/graph/mailboxes/{mailbox.id}/subscriptions/ensure"
    )
    assert response.status_code == 202
    assert len(response.json()["job_ids"]) == 1
    job = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.ENSURE_SUBSCRIPTION.value)
    )
    assert job is not None


def test_mutations_disabled_in_production() -> None:
    class ProdSettings:
        app_env = "production"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        _require_mutations_enabled(ProdSettings())
    assert excinfo.value.status_code == 403


async def test_metrics_endpoint_exposes_prometheus_text(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "graph_webhook_requests_total" in response.text
    assert "graph_jobs_pending" in response.text
