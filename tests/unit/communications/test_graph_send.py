import httpx
import pytest
import respx
from httpx import Response

from app.graph.client import GraphHttpClient
from app.graph.send import GraphSendClient
from tests.conftest import FakeTokenProvider, make_test_settings


@respx.mock
async def test_existing_draft_send_is_one_post_and_202_is_only_accepted() -> None:
    settings = make_test_settings("postgresql+asyncpg://u:p@localhost/db")
    graph = GraphHttpClient(settings, FakeTokenProvider())
    route = respx.post(
        "https://graph.microsoft.com/v1.0/users/shared%40example.invalid/messages/immutable/send"
    ).mock(return_value=Response(202, headers={"request-id": "safe-request"}))
    try:
        result = await GraphSendClient(graph).send_existing_draft(
            "shared@example.invalid", "immutable"
        )
    finally:
        await graph.aclose()
    assert route.call_count == 1
    assert result.http_status == 202
    assert result.request_id == "safe-request"


@respx.mock
async def test_send_client_never_uses_one_step_sendmail_or_reply() -> None:
    settings = make_test_settings("postgresql+asyncpg://u:p@localhost/db")
    graph = GraphHttpClient(settings, FakeTokenProvider())
    respx.post("https://graph.microsoft.com/v1.0/users/shared/messages/draft-id/send").mock(
        return_value=Response(202)
    )
    try:
        await GraphSendClient(graph).send_existing_draft("shared", "draft-id")
    finally:
        await graph.aclose()
    urls = [str(call.request.url) for call in respx.calls]
    assert all(
        "sendMail" not in url and "replyAll" not in url and "/reply" not in url for url in urls
    )


async def test_ambiguous_transport_failure_is_not_retried() -> None:
    calls = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic lost response", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    graph = GraphHttpClient(
        make_test_settings("postgresql+asyncpg://u:p@localhost/db"),
        FakeTokenProvider(),
        http_client=http,
    )
    with pytest.raises(httpx.ReadTimeout):
        await GraphSendClient(graph).send_existing_draft("shared", "draft-id")
    await graph.aclose()
    assert calls == 1
