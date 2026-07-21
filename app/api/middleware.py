"""Correlation-ID and request-logging middleware."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.constants import CORRELATION_ID_HEADER
from app.core.correlation import (
    new_correlation_id,
    parse_correlation_id,
    set_correlation_id,
)
from app.core.logging import log_with_fields

logger = logging.getLogger("app.request")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = parse_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        correlation_id = incoming or new_correlation_id()
        set_correlation_id(correlation_id)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        response.headers[CORRELATION_ID_HEADER] = str(correlation_id)
        log_with_fields(
            logger,
            logging.INFO,
            "request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
