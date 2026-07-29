"""One-shot source-message move; ambiguous results require reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app.graph.client import GraphHttpClient


@dataclass(frozen=True)
class GraphMoveResult:
    message_id: str
    parent_folder_id: str
    request_id: str | None
    client_request_id: str


class GraphMoveClient:
    def __init__(self, graph: GraphHttpClient) -> None:
        self.graph = graph

    async def move(
        self, mailbox: str, immutable_source_id: str, destination_folder_id: str
    ) -> GraphMoveResult:
        url = self.graph.build_url(
            f"users/{quote(mailbox, safe='')}/messages/{quote(immutable_source_id, safe='')}/move"
        )
        response, client_request_id = await self.graph.request_once(
            "POST", url, json_body={"destinationId": destination_folder_id}
        )
        if response.status_code != 201:
            raise ValueError("Graph move did not return 201 Created.")
        payload = self.graph._parse_json(response)
        message_id = str(payload.get("id") or "")
        parent_folder_id = str(payload.get("parentFolderId") or "")
        if not message_id or parent_folder_id != destination_folder_id:
            raise ValueError("Graph move response did not verify the destination folder.")
        return GraphMoveResult(
            message_id, parent_folder_id, response.headers.get("request-id"), client_request_id
        )
