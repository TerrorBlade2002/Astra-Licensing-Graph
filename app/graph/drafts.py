"""Graph reply-draft operations; creation never sends."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.graph.client import GraphHttpClient


class GraphDraftClient:
    def __init__(self, graph: GraphHttpClient) -> None:
        self.graph = graph

    def _message_url(self, mailbox: str, message_id: str) -> str:
        return self.graph.build_url(
            f"users/{quote(mailbox, safe='')}/messages/{quote(message_id, safe='')}"
        )

    async def create_reply(
        self, mailbox: str, source_message_id: str, *, reply_all: bool = False
    ) -> dict[str, Any]:
        operation = "createReplyAll" if reply_all else "createReply"
        response, _ = await self.graph.request_once(
            "POST", f"{self._message_url(mailbox, source_message_id)}/{operation}", json_body={}
        )
        payload = self.graph._parse_json(response)
        if not payload.get("id") or payload.get("isDraft") is not True:
            raise ValueError("Graph did not return a reviewable draft.")
        return payload

    async def get(self, mailbox: str, draft_id: str) -> dict[str, Any]:
        return await self.graph.get_json(
            self._message_url(mailbox, draft_id),
            params={
                "$select": (
                    "id,isDraft,subject,body,toRecipients,ccRecipients,bccRecipients,replyTo,"
                    "changeKey,parentFolderId,webLink,internetMessageId,sentDateTime,hasAttachments"
                )
            },
            operation="communication_draft_get",
        )

    async def patch(
        self, mailbox: str, draft_id: str, changes: dict[str, Any], *, etag: str | None = None
    ) -> dict[str, Any]:
        headers = {"If-Match": etag} if etag else None
        return await self.graph.patch_json(
            self._message_url(mailbox, draft_id),
            changes,
            headers=headers,
            operation="communication_draft_patch",
        )

    async def reply_candidates(self, mailbox: str, conversation_id: str) -> list[dict[str, Any]]:
        """Return draft-folder candidates for an ambiguous createReply.

        The service accepts a candidate only when this query produces one
        unambiguous draft for the source conversation.
        """
        escaped = conversation_id.replace("'", "''")
        payload = await self.graph.get_json(
            self.graph.build_url(f"users/{quote(mailbox, safe='')}/mailFolders/drafts/messages"),
            params={
                "$filter": f"conversationId eq '{escaped}'",
                "$select": (
                    "id,isDraft,conversationId,subject,body,toRecipients,ccRecipients,"
                    "bccRecipients,replyTo,changeKey,parentFolderId,webLink,"
                    "createdDateTime,hasAttachments"
                ),
                "$top": "10",
            },
            operation="communication_draft_reconcile_candidates",
        )
        rows = payload.get("value", [])
        return (
            [row for row in rows if isinstance(row, dict) and row.get("isDraft") is True]
            if isinstance(rows, list)
            else []
        )

    async def attachments(self, mailbox: str, draft_id: str) -> list[dict[str, Any]]:
        payload = await self.graph.get_json(
            f"{self._message_url(mailbox, draft_id)}/attachments",
            params={"$select": "id,name,contentType,size,isInline"},
            operation="communication_draft_attachments",
        )
        rows = payload.get("value", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
