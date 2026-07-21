"""Graph lifecycle-notification webhook endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import SessionDep, SettingsDep
from app.webhooks.graph_messages import handle_webhook

router = APIRouter(prefix="/webhooks/microsoft-graph", tags=["webhooks"])


@router.post("/lifecycle")
async def graph_lifecycle_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    validation_token: Annotated[str | None, Query(alias="validationToken")] = None,
) -> Response:
    return await handle_webhook(
        request,
        session,
        settings,
        validation_token,
        endpoint="lifecycle",
        is_lifecycle=True,
    )
