"""Resilient asynchronous Microsoft Graph HTTP client.

Raw HTTPX is used deliberately: retry behaviour stays explicit, continuation
URLs are validated before use, response headers are captured, and binary
bodies are streamed instead of buffered.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.core.metrics import (
    GRAPH_429_TOTAL,
    GRAPH_REQUEST_DURATION_SECONDS,
    GRAPH_REQUESTS_TOTAL,
    GRAPH_RETRIES_TOTAL,
)
from app.evidence.base import EvidenceStore, EvidenceWriteResult
from app.graph.auth import GraphTokenProvider
from app.graph.errors import GraphApiError, GraphAuthError
from app.graph.retry import (
    backoff_delay,
    is_retryable_exception,
    is_retryable_status,
    parse_retry_after,
)
from app.graph.urls import validate_graph_url

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = frozenset({200, 201, 202, 204})


def _graph_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        return str(code) if code else None
    return None


def _api_error(response: httpx.Response, client_request_id: str) -> GraphApiError:
    return GraphApiError(
        status_code=response.status_code,
        graph_error_code=_graph_error_code(response),
        safe_message=f"Microsoft Graph returned HTTP {response.status_code}.",
        request_id=response.headers.get("request-id"),
        client_request_id=client_request_id,
        retry_after_seconds=parse_retry_after(response.headers.get("Retry-After")),
    )


class GraphHttpClient:
    def __init__(
        self,
        settings: Settings,
        token_provider: GraphTokenProvider,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._token_provider = token_provider
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.graph_connect_timeout_seconds,
                read=settings.graph_read_timeout_seconds,
                write=settings.graph_write_timeout_seconds,
                pool=settings.graph_pool_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=settings.graph_max_connections,
                max_keepalive_connections=settings.graph_max_keepalive_connections,
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ URLs

    def build_url(self, path: str) -> str:
        return f"{self._settings.graph_base_url}/{path.lstrip('/')}"

    def validate_continuation_url(self, url: str) -> str:
        return validate_graph_url(url, allowed_host=self._settings.graph_allowed_host).url

    # --------------------------------------------------------------- headers

    async def _headers(
        self, *, force_token_refresh: bool, extra: dict[str, str] | None
    ) -> tuple[dict[str, str], str]:
        token = await self._token_provider.get_access_token(force_refresh=force_token_refresh)
        client_request_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Prefer": 'IdType="ImmutableId"',
            "client-request-id": client_request_id,
            "return-client-request-id": "true",
        }
        if extra:
            # Merge Prefer values instead of clobbering the ImmutableId default.
            extra = dict(extra)
            if "Prefer" in extra:
                headers["Prefer"] = f'{extra.pop("Prefer")}, IdType="ImmutableId"'
            headers.update(extra)
        return headers, client_request_id

    # ------------------------------------------------------------- core send

    async def _send_with_retry(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        content_body: bytes | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        operation: str = "request",
    ) -> httpx.Response:
        settings = self._settings
        attempt = 0
        refreshed_after_401 = False
        last_error: GraphApiError | None = None

        while attempt < settings.graph_max_retry_attempts:
            attempt += 1
            request_headers, client_request_id = await self._headers(
                force_token_refresh=refreshed_after_401, extra=headers
            )
            started = time.perf_counter()
            try:
                response = await self._client.request(
                    method,
                    url,
                    json=json_body,
                    content=content_body,
                    params=params,
                    headers=request_headers,
                )
            except Exception as exc:
                duration = time.perf_counter() - started
                GRAPH_REQUESTS_TOTAL.labels(method=method, outcome="network_error").inc()
                GRAPH_REQUEST_DURATION_SECONDS.labels(operation=operation).observe(duration)
                if is_retryable_exception(exc) and attempt < settings.graph_max_retry_attempts:
                    GRAPH_RETRIES_TOTAL.labels(reason="network").inc()
                    await asyncio.sleep(
                        backoff_delay(
                            attempt,
                            base_seconds=1.0,
                            max_seconds=settings.graph_max_retry_delay_seconds,
                        )
                    )
                    continue
                raise GraphApiError(
                    status_code=0,
                    graph_error_code="network_error",
                    safe_message="Network failure calling Microsoft Graph.",
                    client_request_id=client_request_id,
                ) from exc

            duration = time.perf_counter() - started
            GRAPH_REQUESTS_TOTAL.labels(method=method, outcome=str(response.status_code)).inc()
            GRAPH_REQUEST_DURATION_SECONDS.labels(operation=operation).observe(duration)
            self._log_response(operation, method, response, client_request_id, attempt, duration)

            if response.status_code in _SUCCESS_STATUSES:
                return response

            if response.status_code == 401:
                await response.aread()
                if refreshed_after_401:
                    raise GraphAuthError(
                        "Microsoft Graph rejected the access token twice.",
                        error_code="persistent_401",
                    )
                refreshed_after_401 = True
                attempt -= 1  # the forced-refresh retry does not consume an attempt
                continue

            if is_retryable_status(response.status_code):
                await response.aread()
                last_error = _api_error(response, client_request_id)
                if response.status_code == 429:
                    GRAPH_429_TOTAL.inc()
                if attempt < settings.graph_max_retry_attempts:
                    GRAPH_RETRIES_TOTAL.labels(reason=str(response.status_code)).inc()
                    delay = backoff_delay(
                        attempt,
                        base_seconds=1.0,
                        max_seconds=settings.graph_max_retry_delay_seconds,
                        retry_after=last_error.retry_after_seconds,
                    )
                    logger.info(
                        "Retrying Graph request",
                        extra={
                            "extra_fields": {
                                "operation": operation,
                                "status_code": response.status_code,
                                "retry_attempt": attempt,
                                "retry_delay_seconds": round(delay, 2),
                            }
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_error

            await response.aread()
            raise _api_error(response, client_request_id)

        if last_error is not None:
            raise last_error
        raise GraphApiError(status_code=0, safe_message="Graph retry budget exhausted.")

    def _log_response(
        self,
        operation: str,
        method: str,
        response: httpx.Response,
        client_request_id: str,
        attempt: int,
        duration: float,
    ) -> None:
        logger.info(
            "Graph request completed",
            extra={
                "extra_fields": {
                    "operation": operation,
                    "method": method,
                    "status_code": response.status_code,
                    "graph_request_id": response.headers.get("request-id"),
                    "client_request_id": client_request_id,
                    "retry_attempt": attempt,
                    "duration_ms": round(duration * 1000, 2),
                }
            },
        )

    # ------------------------------------------------------------ public API

    async def request_once(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        force_token_refresh: bool = False,
    ) -> tuple[httpx.Response, str]:
        """Execute exactly once.

        Non-idempotent communication operations use this boundary so a lost
        response can be reconciled rather than silently replayed.
        """
        request_headers, client_request_id = await self._headers(
            force_token_refresh=force_token_refresh, extra=headers
        )
        response = await self._client.request(method, url, json=json_body, headers=request_headers)
        if response.status_code not in _SUCCESS_STATUSES:
            raise _api_error(response, client_request_id)
        return response, client_request_id

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        operation: str = "get",
    ) -> dict[str, Any]:
        response = await self._send_with_retry(
            "GET", url, params=params, headers=headers, operation=operation
        )
        return self._parse_json(response)

    async def post_json(
        self,
        url: str,
        json_body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        operation: str = "post",
    ) -> dict[str, Any]:
        response = await self._send_with_retry(
            "POST", url, json_body=json_body, headers=headers, operation=operation
        )
        return self._parse_json(response)

    async def patch_json(
        self,
        url: str,
        json_body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        operation: str = "patch",
    ) -> dict[str, Any]:
        response = await self._send_with_retry(
            "PATCH", url, json_body=json_body, headers=headers, operation=operation
        )
        return self._parse_json(response)

    async def delete(
        self, url: str, *, headers: dict[str, str] | None = None, operation: str = "delete"
    ) -> None:
        await self._send_with_retry("DELETE", url, headers=headers, operation=operation)

    async def put_bytes(
        self,
        url: str,
        data: bytes,
        *,
        headers: dict[str, str] | None = None,
        operation: str = "put",
    ) -> dict[str, Any]:
        response = await self._send_with_retry(
            "PUT", url, content_body=data, headers=headers, operation=operation
        )
        return self._parse_json(response)

    async def download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        headers, client_request_id = await self._headers(force_token_refresh=False, extra=None)
        response = await self._client.get(url, headers=headers, follow_redirects=True)
        if response.status_code not in _SUCCESS_STATUSES:
            raise _api_error(response, client_request_id)
        if len(response.content) > max_bytes:
            raise ValueError("Controlled document exceeds the communication download limit.")
        return response.content

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            from app.graph.errors import GraphResponseInvalidError

            raise GraphResponseInvalidError(
                "Graph returned a non-JSON body where JSON was expected."
            ) from exc
        if not isinstance(payload, dict):
            from app.graph.errors import GraphResponseInvalidError

            raise GraphResponseInvalidError("Graph returned an unexpected JSON shape.")
        return payload

    async def download_to_store(
        self,
        url: str,
        store: EvidenceStore,
        key: str,
        *,
        max_bytes: int,
        content_type: str | None = None,
        operation: str = "download",
    ) -> EvidenceWriteResult:
        """Stream a binary Graph response into the evidence store.

        The whole download is retried on retryable failures; each attempt
        rewrites the destination atomically, so partial output never survives.
        """
        settings = self._settings
        attempt = 0
        refreshed_after_401 = False

        while True:
            attempt += 1
            request_headers, client_request_id = await self._headers(
                force_token_refresh=refreshed_after_401, extra=None
            )
            request_headers["Accept"] = "*/*"
            started = time.perf_counter()
            try:
                async with self._client.stream("GET", url, headers=request_headers) as response:
                    GRAPH_REQUESTS_TOTAL.labels(
                        method="GET", outcome=str(response.status_code)
                    ).inc()
                    if response.status_code == 401 and not refreshed_after_401:
                        refreshed_after_401 = True
                        attempt -= 1
                        continue
                    if response.status_code == 401:
                        raise GraphAuthError(
                            "Microsoft Graph rejected the access token twice.",
                            error_code="persistent_401",
                        )
                    if response.status_code != 200:
                        await response.aread()
                        error = _api_error(response, client_request_id)
                        if error.is_retryable and attempt < settings.graph_max_retry_attempts:
                            GRAPH_RETRIES_TOTAL.labels(reason=str(response.status_code)).inc()
                            if response.status_code == 429:
                                GRAPH_429_TOTAL.inc()
                            await asyncio.sleep(
                                backoff_delay(
                                    attempt,
                                    max_seconds=settings.graph_max_retry_delay_seconds,
                                    retry_after=error.retry_after_seconds,
                                )
                            )
                            continue
                        raise error

                    stream: AsyncIterator[bytes] = response.aiter_bytes()
                    result = await store.put_stream(
                        key,
                        stream,
                        max_bytes=max_bytes,
                        content_type=content_type
                        or response.headers.get("Content-Type", "application/octet-stream"),
                    )
            except Exception as exc:
                if is_retryable_exception(exc) and attempt < settings.graph_max_retry_attempts:
                    GRAPH_RETRIES_TOTAL.labels(reason="network").inc()
                    await asyncio.sleep(
                        backoff_delay(attempt, max_seconds=settings.graph_max_retry_delay_seconds)
                    )
                    continue
                raise

            GRAPH_REQUEST_DURATION_SECONDS.labels(operation=operation).observe(
                time.perf_counter() - started
            )
            return result
