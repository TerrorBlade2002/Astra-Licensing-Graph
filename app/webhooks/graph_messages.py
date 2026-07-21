"""Graph change-notification webhook endpoint.

Fast path only: validate, persist receipts, enqueue durable jobs, return 202.
No Microsoft Graph call ever happens inside this handler.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import SessionDep, SettingsDep
from app.core.metrics import GRAPH_WEBHOOK_REQUESTS_TOTAL
from app.services.graph_notifications import GraphNotificationService
from app.webhooks.validation import validation_token_response

router = APIRouter(prefix="/webhooks/microsoft-graph", tags=["webhooks"])
logger = logging.getLogger(__name__)


class BodyTooLargeError(Exception):
    pass


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                raise BodyTooLargeError
        except ValueError:
            pass
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            raise BodyTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


async def handle_webhook(
    request: Request,
    session: Any,
    settings: Any,
    validation_token: str | None,
    *,
    endpoint: str,
    is_lifecycle: bool,
) -> Response:
    if validation_token is not None:
        GRAPH_WEBHOOK_REQUESTS_TOTAL.labels(endpoint=endpoint, outcome="validation").inc()
        return validation_token_response(validation_token)

    try:
        body = await read_limited_body(request, settings.graph_webhook_max_body_bytes)
    except BodyTooLargeError:
        GRAPH_WEBHOOK_REQUESTS_TOTAL.labels(endpoint=endpoint, outcome="too_large").inc()
        return JSONResponse(status_code=413, content={"detail": "Request body too large."})

    try:
        payload = json.loads(body)
    except ValueError:
        GRAPH_WEBHOOK_REQUESTS_TOTAL.labels(endpoint=endpoint, outcome="malformed").inc()
        return JSONResponse(status_code=400, content={"detail": "Malformed JSON body."})

    items = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        GRAPH_WEBHOOK_REQUESTS_TOTAL.labels(endpoint=endpoint, outcome="malformed").inc()
        return JSONResponse(status_code=400, content={"detail": "Expected a value[] collection."})

    service = GraphNotificationService(session, settings)
    summary = await service.process_collection(items, is_lifecycle=is_lifecycle)
    GRAPH_WEBHOOK_REQUESTS_TOTAL.labels(endpoint=endpoint, outcome="accepted").inc()
    logger.info(
        "Webhook collection processed",
        extra={
            "extra_fields": {
                "endpoint": endpoint,
                "accepted": summary.accepted,
                "duplicates": summary.duplicates,
                "invalid_client_state": summary.invalid_client_state,
                "unknown_subscription": summary.unknown_subscription,
                "malformed": summary.malformed,
            }
        },
    )
    return Response(status_code=202)


@router.post("/messages")
async def graph_messages_webhook(
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
        endpoint="messages",
        is_lifecycle=False,
    )
