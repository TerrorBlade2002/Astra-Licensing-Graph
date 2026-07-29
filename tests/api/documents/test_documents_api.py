from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.documents.test_catalog import make_document


async def test_list_detail_filters_and_restricted_policy(
    session: AsyncSession, client: AsyncClient
) -> None:
    visible, _ = await make_document(session)
    await make_document(session, restricted=True)
    listing = await client.get("/api/v1/documents", headers={"X-Actor-Id": "regular-user"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    filtered = await client.get("/api/v1/documents", params={"jurisdiction": "Colorado"})
    assert filtered.json()["total"] == 2
    detail = await client.get(f"/api/v1/documents/{visible.id}")
    assert detail.status_code == 200
    assert detail.json()["current_version"]["storage_status"] == "AVAILABLE"
    assert len(detail.json()["versions"]) == 1


async def test_approval_reuse_patch_and_preview_disabled(
    session: AsyncSession, client: AsyncClient
) -> None:
    document, _ = await make_document(session)
    approve = await client.post(f"/api/v1/documents/{document.id}/approve")
    assert approve.status_code == 200 and approve.json()["approval_status"] == "APPROVED"
    reuse = await client.post(f"/api/v1/documents/{document.id}/approve-reuse")
    assert reuse.status_code == 200 and reuse.json()["approved_for_reuse"] is True
    refreshed = await client.get(f"/api/v1/documents/{document.id}")
    updated_at = refreshed.json()["document"]["updated_at"]
    patch = await client.patch(
        f"/api/v1/documents/{document.id}",
        json={"expected_updated_at": updated_at, "vendor": "RASI"},
    )
    assert patch.status_code == 200 and patch.json()["vendor"] == "RASI"
    stale = await client.patch(
        f"/api/v1/documents/{document.id}",
        json={"expected_updated_at": updated_at, "vendor": "Cornerstone"},
    )
    assert stale.status_code == 409
    preview = await client.post(f"/api/v1/documents/{document.id}/preview")
    assert preview.status_code == 404


async def test_sharepoint_status_and_admin_jobs(session: AsyncSession, client: AsyncClient) -> None:
    status = await client.get("/api/v1/integrations/sharepoint/status")
    assert status.status_code == 200
    assert status.json()["sharepoint_enabled"] is False
    enqueue = await client.post("/api/v1/integrations/sharepoint/bootstrap")
    assert enqueue.status_code == 202
    repeated = await client.post("/api/v1/integrations/sharepoint/bootstrap")
    assert repeated.json()["created"] is False
    jobs = await client.get("/api/v1/integrations/sharepoint/jobs")
    assert jobs.status_code == 200 and jobs.json()[0]["job_type"] == "BOOTSTRAP_REPOSITORY"


async def test_versions_links_and_lifecycle_transitions(
    session: AsyncSession, client: AsyncClient
) -> None:
    document, version = await make_document(session)
    versions = await client.get(f"/api/v1/documents/{document.id}/versions")
    assert versions.status_code == 200 and versions.json()[0]["id"] == str(version.id)
    detail = await client.get(f"/api/v1/documents/{document.id}/versions/{version.id}")
    assert detail.status_code == 200 and detail.json()["version_number"] == 1
    missing = await client.get(
        f"/api/v1/documents/{document.id}/versions/00000000-0000-0000-0000-000000000000"
    )
    assert missing.status_code == 404

    link = await client.post(
        f"/api/v1/documents/{document.id}/links",
        json={
            "link_type": "VENDOR",
            "linked_external_key": "RASI",
            "relationship": "SUBMITTED_BY",
            "metadata": {"synthetic": True},
        },
    )
    assert link.status_code == 201 and link.json()["link_type"] == "VENDOR"
    removed = await client.delete(f"/api/v1/documents/{document.id}/links/{link.json()['id']}")
    assert removed.status_code == 204

    rejected = await client.post(f"/api/v1/documents/{document.id}/reject")
    assert rejected.json()["approval_status"] == "REJECTED"
    submitted = await client.post(f"/api/v1/documents/{document.id}/submit-review")
    assert submitted.json()["approval_status"] == "PENDING_REVIEW"
    superseded = await client.post(f"/api/v1/documents/{document.id}/supersede")
    assert superseded.json()["lifecycle_status"] == "SUPERSEDED"
    revoked = await client.post(f"/api/v1/documents/{document.id}/revoke-reuse")
    assert revoked.status_code == 200 and revoked.json()["approved_for_reuse"] is False
