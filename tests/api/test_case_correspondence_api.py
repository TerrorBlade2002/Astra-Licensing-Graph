"""Correspondence endpoints: authorization, redaction, and shape."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

READER = {"X-Actor-Id": "reader-1", "X-Actor-Roles": "Licensing.Reader"}
REVIEWER = {"X-Actor-Id": "reviewer-1", "X-Actor-Roles": "Licensing.Reviewer"}


async def test_pending_queue_is_empty_and_well_formed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/case-email-links", headers=READER)
    assert response.status_code == 200
    assert response.json() == []


async def test_confirming_a_link_requires_reviewer_authority(client: AsyncClient) -> None:
    """A reader may see proposals but must not decide them.

    Confirmation decides which entity's correspondence enters a case file, so
    it sits behind the same role as classification review.
    """
    response = await client.post(
        f"/api/v1/case-email-links/{uuid.uuid4()}/confirm",
        json={"reason": "looks right"},
        headers=READER,
    )
    assert response.status_code == 403


async def test_deciding_an_unknown_link_is_not_found(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/case-email-links/{uuid.uuid4()}/confirm", json={}, headers=REVIEWER
    )
    assert response.status_code == 404


async def test_thread_of_an_unknown_case_is_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/compliance-cases/{uuid.uuid4()}/thread", headers=READER)
    assert response.status_code == 404


async def test_renewal_timeline_of_an_unknown_license_is_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/licenses/{uuid.uuid4()}/renewal-timeline", headers=READER)
    assert response.status_code == 404


async def test_thread_response_never_carries_message_bodies(client: AsyncClient) -> None:
    """The thread view lists correspondence; the email endpoints own bodies."""
    from app.schemas.licensing import CaseThreadMessageOut

    fields = set(CaseThreadMessageOut.model_fields)
    assert not fields & {"body_text", "body_html", "body_preview", "body"}
