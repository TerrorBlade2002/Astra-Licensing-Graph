"""Attachment enumeration and download."""

from __future__ import annotations

from typing import Any

from app.evidence.base import EvidenceStore, EvidenceWriteResult
from app.graph.client import GraphHttpClient

ATTACHMENT_SELECT = "id,name,contentType,size,isInline,lastModifiedDateTime"


class GraphAttachmentApi:
    def __init__(self, client: GraphHttpClient) -> None:
        self._client = client

    async def list_attachments(
        self, mailbox_identifier: str, graph_message_id: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = self._client.build_url(
            f"users/{mailbox_identifier}/messages/{graph_message_id}/attachments"
        )
        params: dict[str, Any] | None = {"$select": ATTACHMENT_SELECT}
        while url:
            page = await self._client.get_json(url, params=params, operation="attachment_list")
            items.extend(page.get("value") or [])
            next_link = page.get("@odata.nextLink")
            url = self._client.validate_continuation_url(next_link) if next_link else ""
            params = None
        return items

    async def download_file_attachment(
        self,
        mailbox_identifier: str,
        graph_message_id: str,
        graph_attachment_id: str,
        store: EvidenceStore,
        key: str,
        *,
        max_bytes: int,
        content_type: str | None,
    ) -> EvidenceWriteResult:
        return await self._client.download_to_store(
            self._client.build_url(
                f"users/{mailbox_identifier}/messages/{graph_message_id}"
                f"/attachments/{graph_attachment_id}/$value"
            ),
            store,
            key,
            max_bytes=max_bytes,
            content_type=content_type,
            operation="attachment_download",
        )

    async def get_item_attachment(
        self, mailbox_identifier: str, graph_message_id: str, graph_attachment_id: str
    ) -> dict[str, Any]:
        """itemAttachment content is retrieved as its Graph JSON representation."""
        return await self._client.get_json(
            self._client.build_url(
                f"users/{mailbox_identifier}/messages/{graph_message_id}"
                f"/attachments/{graph_attachment_id}"
            ),
            params={"$expand": "microsoft.graph.itemattachment/item"},
            operation="attachment_item_get",
        )
