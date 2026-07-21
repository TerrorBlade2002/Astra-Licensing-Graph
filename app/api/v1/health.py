"""Liveness and readiness endpoints (mounted at /health, outside /api/v1)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("app.health")


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready")
async def ready(request: Request) -> Any:
    session_factory = request.app.state.session_factory
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed: database unavailable")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}
