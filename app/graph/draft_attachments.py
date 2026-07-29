"""Small attachment and guarded large-upload helpers."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.graph.client import GraphHttpClient


class GraphDraftAttachmentClient:
    def __init__(self, graph: GraphHttpClient) -> None:
        self.graph = graph

    def _url(self, mailbox: str, draft_id: str) -> str:
        return self.graph.build_url(
            f"users/{quote(mailbox, safe='')}/messages/{quote(draft_id, safe='')}/attachments"
        )

    async def add_small(
        self, mailbox: str, draft_id: str, *, filename: str, mime_type: str, content: bytes
    ) -> dict[str, Any]:
        response, _ = await self.graph.request_once(
            "POST",
            self._url(mailbox, draft_id),
            json_body={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename,
                "contentType": mime_type,
                "contentBytes": base64.b64encode(content).decode(),
            },
        )
        if response.status_code != 201:
            raise ValueError("Graph attachment creation did not return 201 Created.")
        return self.graph._parse_json(response)

    async def remove(self, mailbox: str, draft_id: str, attachment_id: str) -> None:
        url = f"{self._url(mailbox, draft_id)}/{quote(attachment_id, safe='')}"
        response, _ = await self.graph.request_once("DELETE", url)
        if response.status_code != 204:
            raise ValueError("Graph attachment deletion did not return 204 No Content.")

    async def upload_large(
        self,
        mailbox: str,
        draft_id: str,
        *,
        filename: str,
        content: bytes,
        chunk_bytes: int,
    ) -> dict[str, Any]:
        session = await self.graph.post_json(
            f"{self._url(mailbox, draft_id)}/createUploadSession",
            json_body={
                "AttachmentItem": {
                    "attachmentType": "file",
                    "name": filename,
                    "size": len(content),
                }
            },
            operation="communication_attachment_session",
        )
        upload_url = str(session.get("uploadUrl") or "")
        if not upload_url:
            raise ValueError("Graph did not return an attachment upload session.")
        parsed = urlsplit(upload_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Graph returned an unsafe attachment upload session.")
        result: dict[str, Any] = {}
        # Upload URLs are opaque and deliberately never logged or persisted.
        async with httpx.AsyncClient(timeout=60) as client:
            start = 0
            iterations = 0
            while start < len(content):
                iterations += 1
                if iterations > (len(content) // chunk_bytes) + 8:
                    raise ValueError("Large attachment upload did not make bounded progress.")
                chunk = content[start : start + chunk_bytes]
                end = start + len(chunk) - 1
                try:
                    response = await client.put(
                        upload_url,
                        content=chunk,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{len(content)}",
                        },
                    )
                except httpx.HTTPError:
                    # HTTPX exceptions include the signed upload URL. Never let
                    # that URL reach logs, job errors, or API responses.
                    raise ValueError("Large attachment range upload failed.") from None
                if response.status_code not in {200, 201, 202}:
                    raise ValueError(
                        f"Large attachment range upload returned HTTP {response.status_code}."
                    )
                payload: dict[str, Any] = {}
                if response.content:
                    try:
                        decoded = response.json()
                    except ValueError:
                        raise ValueError(
                            "Large attachment range upload returned invalid JSON."
                        ) from None
                    if isinstance(decoded, dict):
                        payload = decoded
                        result = decoded
                if result.get("id"):
                    break
                expected = payload.get("nextExpectedRanges")
                next_start = end + 1
                if isinstance(expected, list) and expected:
                    first = str(expected[0]).split("-", 1)[0]
                    if first.isdigit():
                        next_start = int(first)
                if next_start <= start or next_start > len(content):
                    raise ValueError("Large attachment upload returned an invalid next range.")
                start = next_start
        if not result.get("id"):
            raise ValueError("Large attachment upload did not return a final attachment ID.")
        return result
