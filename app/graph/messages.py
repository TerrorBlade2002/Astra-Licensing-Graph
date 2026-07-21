"""Full-message and raw-MIME retrieval."""

from __future__ import annotations

from typing import Any

from app.evidence.base import EvidenceStore, EvidenceWriteResult
from app.graph.client import GraphHttpClient

FULL_MESSAGE_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,bccRecipients,replyTo,receivedDateTime,"
    "sentDateTime,body,bodyPreview,hasAttachments,conversationId,internetMessageId,"
    "isRead,parentFolderId,lastModifiedDateTime"
)


class GraphMessageApi:
    def __init__(self, client: GraphHttpClient) -> None:
        self._client = client

    async def get_full_message(
        self, mailbox_identifier: str, graph_message_id: str
    ) -> dict[str, Any]:
        return await self._client.get_json(
            self._client.build_url(f"users/{mailbox_identifier}/messages/{graph_message_id}"),
            params={"$select": FULL_MESSAGE_SELECT},
            headers={"Prefer": 'outlook.body-content-type="text"'},
            operation="message_get",
        )

    async def download_mime(
        self,
        mailbox_identifier: str,
        graph_message_id: str,
        store: EvidenceStore,
        key: str,
        *,
        max_bytes: int,
    ) -> EvidenceWriteResult:
        return await self._client.download_to_store(
            self._client.build_url(
                f"users/{mailbox_identifier}/messages/{graph_message_id}/$value"
            ),
            store,
            key,
            max_bytes=max_bytes,
            content_type="message/rfc822",
            operation="message_mime",
        )
