"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.metrics import (
    COMMUNICATION_DRAFTS_PENDING_REVIEW,
    COMMUNICATION_DRAFTS_PENDING_SEND_APPROVAL,
    COMMUNICATION_OLDEST_PENDING_APPROVAL_AGE_SECONDS,
    METRICS_CONTENT_TYPE,
    render_metrics,
)
from app.db.session import create_engine, create_session_factory
from app.models import OutboundDraft
from app.models.mixins import utcnow
from app.webhooks.graph_lifecycle import router as graph_lifecycle_router
from app.webhooks.graph_messages import router as graph_messages_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(CorrelationIdMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(graph_messages_router)
    app.include_router(graph_lifecycle_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        try:
            async with app.state.session_factory() as session:
                pending_review = await session.scalar(
                    select(func.count(OutboundDraft.id)).where(
                        OutboundDraft.draft_status.in_(["REVIEW_IN_PROGRESS", "CHANGES_REQUESTED"])
                    )
                )
                pending_approval = await session.scalar(
                    select(func.count(OutboundDraft.id)).where(
                        OutboundDraft.draft_status == "PENDING_SEND_APPROVAL"
                    )
                )
                oldest = await session.scalar(
                    select(func.min(OutboundDraft.submitted_for_approval_at)).where(
                        OutboundDraft.draft_status == "PENDING_SEND_APPROVAL"
                    )
                )
                COMMUNICATION_DRAFTS_PENDING_REVIEW.set(int(pending_review or 0))
                COMMUNICATION_DRAFTS_PENDING_SEND_APPROVAL.set(int(pending_approval or 0))
                COMMUNICATION_OLDEST_PENDING_APPROVAL_AGE_SECONDS.set(
                    max(0.0, (utcnow() - oldest).total_seconds()) if oldest else 0.0
                )
        except SQLAlchemyError:
            # Health endpoints remain responsible for reporting database
            # readiness; metrics rendering itself must stay available.
            pass
        return Response(content=render_metrics(), media_type=METRICS_CONTENT_TYPE)

    return app


app = create_app()
