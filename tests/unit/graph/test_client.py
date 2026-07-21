"""GraphHttpClient behaviour against respx-mocked endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.graph.client import GraphHttpClient
from app.graph.errors import GraphApiError, GraphAuthError, GraphResponseInvalidError

BASE = "https://graph.microsoft.com/v1.0"


@respx.mock
async def test_get_json_sends_required_headers(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"ok": True}))
    payload = await graph_client.get_json(f"{BASE}/me")
    assert payload == {"ok": True}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer synthetic-test-token"
    assert 'IdType="ImmutableId"' in request.headers["Prefer"]
    assert request.headers["return-client-request-id"] == "true"
    assert request.headers["client-request-id"]


@respx.mock
async def test_extra_prefer_headers_are_merged(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/msg").mock(return_value=httpx.Response(200, json={}))
    await graph_client.get_json(
        f"{BASE}/msg", headers={"Prefer": 'outlook.body-content-type="text"'}
    )
    prefer = route.calls.last.request.headers["Prefer"]
    assert 'outlook.body-content-type="text"' in prefer
    assert 'IdType="ImmutableId"' in prefer


@respx.mock
async def test_401_refreshes_token_and_retries_once(
    graph_client: GraphHttpClient, fake_token_provider
) -> None:
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": 1})]
    )
    payload = await graph_client.get_json(f"{BASE}/x")
    assert payload == {"ok": 1}
    assert route.call_count == 2
    assert fake_token_provider.force_refreshes == 1


@respx.mock
async def test_persistent_401_raises_auth_error(graph_client: GraphHttpClient) -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401))
    with pytest.raises(GraphAuthError) as excinfo:
        await graph_client.get_json(f"{BASE}/x")
    assert excinfo.value.error_code == "persistent_401"
    assert "synthetic-test-token" not in str(excinfo.value)


@respx.mock
async def test_429_honours_retry_after(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/throttle").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"done": True}),
        ]
    )
    payload = await graph_client.get_json(f"{BASE}/throttle")
    assert payload == {"done": True}
    assert route.call_count == 2


@respx.mock
async def test_503_retries_with_backoff_then_fails(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/down").mock(return_value=httpx.Response(503))
    with pytest.raises(GraphApiError) as excinfo:
        await graph_client.get_json(f"{BASE}/down")
    assert excinfo.value.status_code == 503
    assert excinfo.value.is_retryable
    assert route.call_count == 3  # GRAPH_MAX_RETRY_ATTEMPTS in test settings


@respx.mock
async def test_400_is_not_retried_and_is_sanitized(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/bad").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "BadRequest",
                    "message": "Confidential email body should not leak",
                }
            },
            headers={"request-id": "req-42"},
        )
    )
    with pytest.raises(GraphApiError) as excinfo:
        await graph_client.get_json(f"{BASE}/bad")
    error = excinfo.value
    assert route.call_count == 1
    assert error.status_code == 400
    assert error.graph_error_code == "BadRequest"
    assert error.request_id == "req-42"
    assert not error.is_retryable
    assert "Confidential" not in str(error) + str(error.details)


@respx.mock
async def test_network_errors_are_retried(graph_client: GraphHttpClient) -> None:
    route = respx.get(f"{BASE}/net").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": 1})]
    )
    assert await graph_client.get_json(f"{BASE}/net") == {"ok": 1}
    assert route.call_count == 2


@respx.mock
async def test_non_json_success_body_raises_invalid(graph_client: GraphHttpClient) -> None:
    respx.get(f"{BASE}/weird").mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>")
    )
    with pytest.raises(GraphResponseInvalidError):
        await graph_client.get_json(f"{BASE}/weird")


@respx.mock
async def test_download_to_store_streams_and_hashes(
    graph_client: GraphHttpClient, evidence_store
) -> None:
    body = b"%PDF-1.7 synthetic content" * 10
    respx.get(f"{BASE}/users/u/messages/m/$value").mock(
        return_value=httpx.Response(200, content=body)
    )
    result = await graph_client.download_to_store(
        f"{BASE}/users/u/messages/m/$value",
        evidence_store,
        "mailboxes/m/emails/e/message.eml",
        max_bytes=10_000,
    )
    assert result.bytes_written == len(body)
    assert await evidence_store.open("mailboxes/m/emails/e/message.eml") == body
