"""Aggregated /api/v1 router."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.v1 import (
    audit,
    case_correspondence,
    classification_reviews,
    communications,
    compliance_cases,
    dashboard,
    deadlines,
    document_operations,
    document_packets,
    documents,
    emails,
    form_preparation,
    graph_jobs,
    graph_status,
    graph_subscriptions,
    information_registry,
    legal_entities,
    license_inventory,
    licensing_admin,
    licensing_dashboard,
    mailboxes,
    operations,
    portal_auth,
    portal_definitions,
    portal_runs,
    portal_tasks,
    requirement_matrix,
    requirement_sources,
    sharepoint_status,
    submission_evidence,
    tasks,
    taxonomy,
    tracker_imports,
)
from app.schemas.event import SystemVersionOut

api_router = APIRouter()
api_router.include_router(document_operations.router)
api_router.include_router(documents.router)
api_router.include_router(mailboxes.router)
api_router.include_router(emails.router)
api_router.include_router(tasks.router)
api_router.include_router(audit.router)
api_router.include_router(graph_status.router)
api_router.include_router(graph_jobs.router)
api_router.include_router(graph_subscriptions.router)
api_router.include_router(sharepoint_status.router)
api_router.include_router(sharepoint_status.storage_router)
api_router.include_router(portal_auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(classification_reviews.router)
api_router.include_router(communications.router)
api_router.include_router(portal_tasks.router)
api_router.include_router(taxonomy.router)
api_router.include_router(legal_entities.router)
api_router.include_router(license_inventory.router)
api_router.include_router(requirement_matrix.router)
api_router.include_router(requirement_sources.router)
api_router.include_router(compliance_cases.router)
api_router.include_router(case_correspondence.router)
api_router.include_router(deadlines.router)
api_router.include_router(information_registry.router)
api_router.include_router(document_packets.router)
api_router.include_router(form_preparation.router)
api_router.include_router(tracker_imports.router)
api_router.include_router(licensing_dashboard.router)
api_router.include_router(licensing_admin.router)
api_router.include_router(portal_definitions.router)
api_router.include_router(portal_runs.router)
api_router.include_router(submission_evidence.router)
api_router.include_router(operations.router)

system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/version", response_model=SystemVersionOut)
async def system_version(request: Request) -> SystemVersionOut:
    settings = request.app.state.settings
    revision: str | None = None
    try:
        async with request.app.state.session_factory() as session:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            revision = row[0] if row else None
    except Exception:
        revision = None
    return SystemVersionOut(
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.app_env,
        migration_revision=revision,
    )


api_router.include_router(system_router)
