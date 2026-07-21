"""Email/task/mailbox endpoint tests using seeded synthetic data."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli.seed_dev import SEED_TASK_KEY, seed


async def _seed(session: AsyncSession) -> None:
    outcome = await seed(session)
    assert outcome == "seeded"
    await session.commit()


async def test_mailbox_list_and_folders(session: AsyncSession, client: AsyncClient) -> None:
    await _seed(session)
    response = await client.get("/api/v1/mailboxes")
    assert response.status_code == 200
    mailboxes = response.json()
    assert len(mailboxes) == 1
    assert mailboxes[0]["address"] == "astralicensing@astraglobal.com"

    folders = await client.get(f"/api/v1/mailboxes/{mailboxes[0]['id']}/folders")
    assert folders.status_code == 200
    names = {f["display_name"] for f in folders.json()}
    assert "08_Info_Required" in names and "99_Errors_Review" in names


async def test_email_list_pagination_and_filters(
    session: AsyncSession, client: AsyncClient
) -> None:
    await _seed(session)

    listing = await client.get("/api/v1/emails")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["page"] == 1 and body["page_size"] == 50
    item = body["items"][0]
    assert item["processing_state"] == "COMPLETED"
    # List endpoints never include body content.
    assert "body_text" not in item and "body" not in item

    filtered = await client.get("/api/v1/emails", params={"processing_state": "DISCOVERED"})
    assert filtered.json()["total"] == 0

    filtered = await client.get(
        "/api/v1/emails",
        params={"sender_email": "SYNTHETIC.SENDER@example.invalid", "has_attachments": False},
    )
    assert filtered.json()["total"] == 1

    filtered = await client.get("/api/v1/emails", params={"subject_contains": "colorado"})
    assert filtered.json()["total"] == 1


async def test_email_detail_without_and_with_body(
    session: AsyncSession, client: AsyncClient
) -> None:
    await _seed(session)
    email_id = (await client.get("/api/v1/emails")).json()["items"][0]["id"]

    detail = await client.get(f"/api/v1/emails/{email_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["body"] is None
    assert body["recipients"][0]["address"] == "astralicensing@astraglobal.com"
    assert body["current_classification"]["vendor"] == "RASI"
    assert body["latest_review"]["decision"] == "APPROVED"
    assert body["task"]["task_key"] == SEED_TASK_KEY
    assert body["recent_events"][0]["to_state"] == "DISCOVERED"
    assert body["recent_events"][-1]["to_state"] == "COMPLETED"

    with_body = await client.get(f"/api/v1/emails/{email_id}", params={"include_body": "true"})
    assert with_body.json()["body"]["body_text"].startswith("Synthetic seed record")


async def test_email_events_endpoint(session: AsyncSession, client: AsyncClient) -> None:
    await _seed(session)
    email_id = (await client.get("/api/v1/emails")).json()["items"][0]["id"]
    events = await client.get(f"/api/v1/emails/{email_id}/events")
    assert events.status_code == 200
    states = [e["to_state"] for e in events.json()]
    assert states == [
        "DISCOVERED",
        "FETCHED",
        "ATTACHMENTS_SAVED",
        "CLASSIFIED",
        "TASK_CREATED",
        "MOVED",
        "COMPLETED",
    ]
    missing = await client.get(f"/api/v1/emails/{uuid.uuid4()}/events")
    assert missing.status_code == 404


async def test_task_list_filters_and_detail(session: AsyncSession, client: AsyncClient) -> None:
    await _seed(session)

    tasks = await client.get("/api/v1/tasks")
    assert tasks.json()["total"] == 1

    assert (await client.get("/api/v1/tasks", params={"status": "OPEN"})).json()["total"] == 0
    assert (
        await client.get("/api/v1/tasks", params={"status": "COMPLETED", "vendor": "RASI"})
    ).json()["total"] == 1
    assert (await client.get("/api/v1/tasks", params={"state": "Colorado"})).json()["total"] == 1
    assert (await client.get("/api/v1/tasks", params={"state": "Texas"})).json()["total"] == 0
    assert (await client.get("/api/v1/tasks", params={"due_before": "2026-08-01"})).json()[
        "total"
    ] == 1
    assert (await client.get("/api/v1/tasks", params={"due_before": "2026-07-01"})).json()[
        "total"
    ] == 0

    task_id = tasks.json()["items"][0]["id"]
    detail = await client.get(f"/api/v1/tasks/{task_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["queue"] == "08_Info_Required"
    assert len(body["requested_items"]) == 3
    assert body["requested_items"][0]["sort_order"] == 0


async def test_audit_events_endpoint(session: AsyncSession, client: AsyncClient) -> None:
    await _seed(session)
    response = await client.get("/api/v1/audit-events", params={"entity_type": "email"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    first = body["items"][0]
    assert first["action"] == "seed_dev"
    # No secret-bearing payloads on the wire.
    assert "before_data" not in first and "after_data" not in first
