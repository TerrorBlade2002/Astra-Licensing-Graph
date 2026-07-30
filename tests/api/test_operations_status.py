"""Milestone 8: health, readiness, and the operations status endpoint."""

from __future__ import annotations

import json

from httpx import AsyncClient


async def test_liveness_and_readiness(client: AsyncClient) -> None:
    live = await client.get("/health/live")
    assert live.status_code == 200
    assert live.json() == {"status": "alive"}

    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


async def test_operations_status_reports_the_deployment_picture(client: AsyncClient) -> None:
    response = await client.get("/api/v1/operations/status")
    assert response.status_code == 200
    body = response.json()

    for field in (
        "api_status",
        "database_status",
        "last_inbox_sync_at",
        "pending_jobs",
        "failed_review_jobs",
        "last_scheduler_run_at",
        "worker_heartbeat_age_seconds",
        "graph",
        "sharepoint",
        "alerts",
        "queues",
    ):
        assert field in body, field

    assert body["api_status"] == "OK"
    assert body["database_status"] == "OK"
    assert body["pending_jobs"] == 0
    assert body["failed_review_jobs"] == 0
    assert set(body["queues"]) == {
        "graph",
        "documents",
        "communications",
        "licensing",
        "portals",
    }


async def test_operations_status_reports_a_missing_worker(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/operations/status")).json()
    codes = {alert["code"] for alert in body["alerts"]}
    assert "WORKER_NOT_RUNNING" in codes


async def test_operations_status_confirms_the_mandatory_controls(client: AsyncClient) -> None:
    controls = (await client.get("/api/v1/operations/status")).json()["controls"]
    assert controls["human_review_required"] is True
    assert controls["send_approval_required"] is True
    assert controls["portal_final_submit_human_only"] is True
    assert controls["external_form_submission_enabled"] is False


async def test_read_only_dashboards_respond_on_an_empty_database(client: AsyncClient) -> None:
    """Every operator-facing read endpoint must answer, not 500.

    A deployed licensing dashboard returned 500 from a `.not_in_(` typo that no
    test exercised; these are cheap smoke checks against an empty schema.
    """
    for path in (
        "/api/v1/licensing-dashboard/summary",
        "/api/v1/licensing-dashboard/upcoming-deadlines",
        "/api/v1/licensing-dashboard/stale-information",
        "/api/v1/licensing-dashboard/missing-documents",
        "/api/v1/licensing-dashboard/blocked-cases",
        "/api/v1/licensing-dashboard/data-quality",
        "/api/v1/integrations/graph/status",
        "/api/v1/integrations/sharepoint/status",
        "/api/v1/operations/status",
        "/api/v1/system/version",
    ):
        response = await client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"


async def test_operations_status_exposes_no_secret_or_delta_link(client: AsyncClient) -> None:
    payload = json.dumps((await client.get("/api/v1/operations/status")).json()).lower()
    for forbidden in (
        "secret",
        "password",
        "delta",
        "authorization",
        "bearer",
        "postgresql",
        "@",
    ):
        assert forbidden not in payload, forbidden
