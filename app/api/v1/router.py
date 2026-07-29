"""Aggregated /api/v1 router."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.v1 import (
    audit,
    classification_reviews,
    communications,
    dashboard,
    document_operations,
    documents,
    emails,
    graph_jobs,
    graph_status,
    graph_subscriptions,
    mailboxes,
    portal_auth,
    portal_tasks,
    sharepoint_status,
    tasks,
    taxonomy,
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
api_router.include_router(portal_auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(classification_reviews.router)
api_router.include_router(communications.router)
api_router.include_router(portal_tasks.router)
api_router.include_router(taxonomy.router)

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
