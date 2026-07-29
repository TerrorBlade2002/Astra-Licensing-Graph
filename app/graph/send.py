"""One-shot send of an existing immutable Graph draft."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app.graph.client import GraphHttpClient


@dataclass(frozen=True)
class GraphSendAccepted:
    http_status: int
    request_id: str | None
    client_request_id: str


class GraphSendClient:
    def __init__(self, graph: GraphHttpClient) -> None:
        self.graph = graph

    async def send_existing_draft(
        self, mailbox: str, immutable_draft_id: str, *, force_token_refresh: bool = False
    ) -> GraphSendAccepted:
        url = self.graph.build_url(
            f"users/{quote(mailbox, safe='')}/messages/{quote(immutable_draft_id, safe='')}/send"
        )
        response, client_request_id = await self.graph.request_once(
            "POST", url, json_body={}, force_token_refresh=force_token_refresh
        )
        if response.status_code != 202:
            raise ValueError("Graph send did not return 202 Accepted.")
        return GraphSendAccepted(
            http_status=202,
            request_id=response.headers.get("request-id"),
            client_request_id=client_request_id,
        )
