from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import respx
from httpx import Response

from app.communications.attachments import transmission_blockers
from app.graph.client import GraphHttpClient
from app.graph.draft_attachments import GraphDraftAttachmentClient
from tests.conftest import FakeTokenProvider, make_test_settings


def test_transmission_policy_rechecks_expiry_approval_quarantine_and_hash() -> None:
    document = SimpleNamespace(
        id="document",
        lifecycle_status="ACTIVE",
        approval_status="APPROVED",
        approved_for_reuse=True,
        expiry_date=date.today() - timedelta(days=1),
        current_version_id="current",
        content_sha256="approved-hash",
        size_bytes=12,
        confidentiality_level="CONFIDENTIAL",
    )
    version = SimpleNamespace(
        id="different",
        document_id="document",
        storage_status="QUARANTINED",
        content_sha256="changed-hash",
        size_bytes=13,
    )
    assert set(transmission_blockers(document, version)) >= {
        "DOCUMENT_EXPIRED",
        "DOCUMENT_QUARANTINED",
        "DOCUMENT_SUPERSEDED",
        "DOCUMENT_HASH_INVALID",
    }


@respx.mock
async def test_large_shared_mailbox_upload_is_sequential_and_has_no_bearer_token() -> None:
    graph = GraphHttpClient(
        make_test_settings("postgresql+asyncpg://u:p@localhost/db"),
        FakeTokenProvider(),
    )
    session_route = respx.post(
        "https://graph.microsoft.com/v1.0/users/shared/messages/draft/attachments/"
        "createUploadSession"
    ).mock(return_value=Response(200, json={"uploadUrl": "https://upload.example.invalid/opaque"}))
    upload_route = respx.put("https://upload.example.invalid/opaque").mock(
        side_effect=[
            Response(202, json={"nextExpectedRanges": ["4-"]}),
            Response(201, json={"id": "attachment-id"}),
        ]
    )
    try:
        result = await GraphDraftAttachmentClient(graph).upload_large(
            "shared",
            "draft",
            filename="synthetic.pdf",
            content=b"abcdefgh",
            chunk_bytes=4,
        )
    finally:
        await graph.aclose()
    assert session_route.call_count == 1
    assert upload_route.call_count == 2
    requests = [call.request for call in upload_route.calls]
    assert [request.headers["Content-Range"] for request in requests] == [
        "bytes 0-3/8",
        "bytes 4-7/8",
    ]
    assert all("Authorization" not in request.headers for request in requests)
    assert result["id"] == "attachment-id"


@respx.mock
async def test_large_upload_failure_never_exposes_signed_upload_url() -> None:
    graph = GraphHttpClient(
        make_test_settings("postgresql+asyncpg://u:p@localhost/db"),
        FakeTokenProvider(),
    )
    signed_url = "https://upload.example.invalid/secret-signed-query?token=do-not-log"
    respx.post(
        "https://graph.microsoft.com/v1.0/users/shared/messages/draft/attachments/"
        "createUploadSession"
    ).mock(return_value=Response(200, json={"uploadUrl": signed_url}))
    respx.put(signed_url).mock(return_value=Response(500))
    try:
        with pytest.raises(ValueError) as exc_info:
            await GraphDraftAttachmentClient(graph).upload_large(
                "shared",
                "draft",
                filename="synthetic.pdf",
                content=b"abcd",
                chunk_bytes=4,
            )
    finally:
        await graph.aclose()
    assert signed_url not in str(exc_info.value)
    assert "do-not-log" not in str(exc_info.value)
