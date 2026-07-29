from app.classification.orchestration import ClassificationOrchestrator
from tests.conftest import create_email, create_mailbox, make_test_settings


async def test_portal_review_and_task_api_flow(client, session, test_database_url) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(
        session,
        mailbox,
        processing_state="ATTACHMENTS_SAVED",
        sender_email="licensing@rasi.com",
        subject="Colorado Collection Agency License information required",
        body_text=(
            "Please provide:\n- Current toll-free telephone number\n"
            "The requested information is due by July 31, 2026."
        ),
    )
    await session.commit()
    classification = await ClassificationOrchestrator(
        session, make_test_settings(test_database_url)
    ).classify_email(email.id)

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert "manage_rules" in me.json()["capabilities"]

    queue = await client.get("/api/v1/classification-reviews?status=PENDING")
    assert queue.status_code == 200
    assert queue.json()[0]["classification"]["vendor"] == "RASI"

    detail = await client.get(f"/api/v1/classification-reviews/{classification.id}")
    assert detail.status_code == 200
    review = detail.json()["review"]
    assert "Current toll-free" in detail.json()["current_message_body"]

    denied = await client.post(
        f"/api/v1/classification-reviews/{classification.id}/claim",
        json={"expected_revision": 1},
        headers={"X-Actor-Roles": "Licensing.Reader"},
    )
    assert denied.status_code == 403

    claimed = await client.post(
        f"/api/v1/classification-reviews/{classification.id}/claim",
        json={"expected_revision": 1},
    )
    assert claimed.status_code == 200
    assert claimed.json()["revision"] == 2

    filtered = await client.get(
        "/api/v1/classification-reviews",
        params={
            "status": "IN_REVIEW",
            "vendor": detail.json()["classification"]["vendor"],
            "email_type": detail.json()["classification"]["email_type"],
            "state": detail.json()["classification"]["states"][0],
            "confidence_min": 0.1,
            "confidence_max": 1.0,
            "claimed_by": claimed.json()["reviewer_principal"],
        },
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    released = await client.post(
        f"/api/v1/classification-reviews/{classification.id}/release",
        json={"expected_revision": 2},
    )
    assert released.status_code == 200
    reclaimed = await client.post(
        f"/api/v1/classification-reviews/{classification.id}/claim",
        json={"expected_revision": 3},
    )
    assert reclaimed.status_code == 200

    approved = await client.post(
        f"/api/v1/classification-reviews/{classification.id}/approve",
        json={"expected_revision": 4},
    )
    assert approved.status_code == 200

    created = await client.post(
        f"/api/v1/classification-reviews/{review['id']}/create-task", json={}
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    task_list = await client.get(
        "/api/v1/licensing-tasks",
        params={
            "status": created.json()["status"],
            "queue": created.json()["queue"],
        },
    )
    assert task_list.status_code == 200
    assert [row["id"] for row in task_list.json()] == [task_id]

    patched_task = await client.patch(
        f"/api/v1/licensing-tasks/{task_id}",
        json={
            "due_date": "2026-07-31",
            "priority": "HIGH",
            "notes": "Confirm regulator response.",
        },
    )
    assert patched_task.status_code == 200
    assert patched_task.json()["priority"] == "HIGH"
    due_filtered = await client.get(
        "/api/v1/licensing-tasks",
        params={"due_before": "2026-08-01", "due_after": "2026-07-01"},
    )
    assert [row["id"] for row in due_filtered.json()] == [task_id]

    assigned = await client.post(
        f"/api/v1/licensing-tasks/{task_id}/assign",
        json={"assigned_to": "owner@astra.example"},
    )
    assert assigned.status_code == 200
    transitioned = await client.post(
        f"/api/v1/licensing-tasks/{task_id}/transition", json={"status": "IN_REVIEW"}
    )
    assert transitioned.status_code == 200
    comment = await client.post(
        f"/api/v1/licensing-tasks/{task_id}/comments",
        json={"body": "Evidence verified with licensing operations."},
    )
    assert comment.status_code == 201
    comments = await client.get(f"/api/v1/licensing-tasks/{task_id}/comments")
    assert comments.status_code == 200
    assert comments.json()[0]["body"].startswith("Evidence verified")
    unsafe_comment = await client.post(
        f"/api/v1/licensing-tasks/{task_id}/comments",
        json={"body": "<script>alert('no')</script>"},
    )
    assert unsafe_comment.status_code == 400

    added_item = await client.post(
        f"/api/v1/licensing-tasks/{task_id}/requested-items",
        json={
            "item_text": "Confirm agency contact",
            "category": "contact_information",
            "required": False,
            "status": "OPEN",
        },
    )
    assert added_item.status_code == 201
    item_id = added_item.json()["id"]
    updated_item = await client.patch(
        f"/api/v1/licensing-tasks/{task_id}/requested-items/{item_id}",
        json={
            "item_text": "Confirm agency contact",
            "category": "contact_information",
            "required": False,
            "status": "VERIFIED",
            "owner": "owner@astra.example",
        },
    )
    assert updated_item.status_code == 200
    assert updated_item.json()["status"] == "VERIFIED"
    deleted_item = await client.delete(
        f"/api/v1/licensing-tasks/{task_id}/requested-items/{item_id}"
    )
    assert deleted_item.status_code == 204

    events = await client.get(f"/api/v1/licensing-tasks/{task_id}/events")
    assert events.status_code == 200
    assert any(event["event_type"] == "REQUESTED_ITEM_UPDATED" for event in events.json())
    task = await client.get(f"/api/v1/licensing-tasks/{task_id}")
    assert task.status_code == 200
    assert any(event["event_type"] == "STATUS_CHANGED" for event in task.json()["events"])
    assert task.json()["draft_required"] is False

    summary = await client.get("/api/v1/dashboard/summary")
    assert summary.status_code == 200
