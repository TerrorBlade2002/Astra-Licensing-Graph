from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.graph.client import GraphHttpClient
from app.sharepoint.client import SharePointClient
from app.sharepoint.errors import SharePointConcurrencyError, SharePointPermissionError
from app.sharepoint.models import UploadSessionInfo


@pytest.mark.asyncio
@respx.mock
async def test_discovery_folder_upload_metadata_and_versions(
    graph_client: GraphHttpClient, graph_settings: Settings
) -> None:
    base = graph_settings.graph_base_url
    respx.get(f"{base}/sites/site-1").mock(
        return_value=httpx.Response(
            200, json={"id": "site-1", "displayName": "Astra", "webUrl": "https://example.invalid"}
        )
    )
    respx.get(f"{base}/sites/site-1/drives?$expand=list").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "drive-1",
                        "name": "Docs",
                        "driveType": "documentLibrary",
                        "list": {"id": "list-1"},
                    }
                ]
            },
        )
    )
    respx.post(f"{base}/drives/drive-1/items/root/children").mock(
        return_value=httpx.Response(
            201, json={"id": "folder-1", "name": "Managed", "size": 0, "folder": {}}
        )
    )
    upload = respx.put(f"{base}/drives/drive-1/items/folder-1:/test.pdf:/content").mock(
        return_value=httpx.Response(
            201, json={"id": "item-1", "name": "test.pdf", "size": 3, "eTag": "etag"}
        )
    )
    respx.patch(f"{base}/sites/site-1/lists/list-1/items/li-1/fields").mock(
        return_value=httpx.Response(200, json={"AstraDocumentKey": "ASTRA-1"})
    )
    respx.get(f"{base}/drives/drive-1/items/item-1/versions").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1.0"}]})
    )
    client = SharePointClient(graph_client, graph_settings)
    try:
        assert (await client.get_site("site-1")).id == "site-1"
        assert (await client.list_drives("site-1"))[0].list_id == "list-1"
        assert (await client.create_folder("drive-1", "root", "Managed")).is_folder
        result = await client.upload_small(
            "drive-1", "folder-1", "test.pdf", b"pdf", content_type="application/pdf"
        )
        assert result.item.id == "item-1" and upload.called
        assert await client.update_list_item_fields(
            "site-1", "list-1", "li-1", {"AstraDocumentKey": "ASTRA-1"}
        )
        assert (await client.list_versions("drive-1", "item-1"))[0]["id"] == "1.0"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_permission_and_etag_errors(
    graph_client: GraphHttpClient, graph_settings: Settings
) -> None:
    base = graph_settings.graph_base_url
    respx.get(f"{base}/sites/denied").mock(
        return_value=httpx.Response(403, json={"error": {"code": "accessDenied"}})
    )
    respx.patch(f"{base}/sites/site/lists/list/items/item/fields").mock(
        return_value=httpx.Response(412, json={"error": {"code": "preconditionFailed"}})
    )
    client = SharePointClient(graph_client, graph_settings)
    try:
        with pytest.raises(SharePointPermissionError):
            await client.get_site("denied")
        with pytest.raises(SharePointConcurrencyError):
            await client.update_list_item_fields("site", "list", "item", {}, etag="old")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_resumable_upload_retries_failed_chunk(
    tmp_path: Path, graph_client: GraphHttpClient, graph_settings: Settings
) -> None:
    settings = graph_settings.model_copy(
        update={"sharepoint_upload_chunk_bytes": 327680, "sharepoint_upload_max_attempts": 3}
    )
    source = tmp_path / "large.bin"
    source.write_bytes(b"a" * 400000)
    upload_url = "https://tenant.sharepoint.com/upload/opaque"
    route = respx.put(upload_url).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(202, json={"nextExpectedRanges": ["327680-"]}),
            httpx.Response(201, json={"id": "item-final", "name": "large.bin", "size": 400000}),
        ]
    )
    client = SharePointClient(graph_client, settings)
    try:
        result = await client.upload_file_session(
            UploadSessionInfo(upload_url, datetime.now(UTC) + timedelta(minutes=5), 0),
            source,
            total_bytes=400000,
        )
        assert result.item.id == "item-final"
        assert route.call_count == 3
        assert "Authorization" not in route.calls[0].request.headers
        assert route.calls[1].request.headers["Content-Range"] == "bytes 0-327679/400000"
        assert route.calls[2].request.headers["Content-Range"] == "bytes 327680-399999/400000"
    finally:
        await client.aclose()
