from __future__ import annotations

from types import SimpleNamespace

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import document_operations
from tests.integration.documents.test_catalog import make_document


class Closable:
    async def aclose(self) -> None:
        pass


class DownloadClient(Closable):
    async def download_to_store(self, drive_id, item_id, store, key, *, max_bytes):
        return await store.put_bytes(key, b"synthetic-pdf", content_type="application/pdf")


async def test_controlled_download_has_safe_headers(
    session: AsyncSession, client: AsyncClient, monkeypatch
) -> None:
    document, _ = await make_document(session)
    monkeypatch.setattr(
        document_operations,
        "_clients",
        lambda settings: (Closable(), DownloadClient(), SimpleNamespace()),
    )
    response = await client.get(f"/api/v1/documents/{document.id}/download")
    assert response.status_code == 200 and response.content == b"synthetic-pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
