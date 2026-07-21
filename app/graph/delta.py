"""Folder delta-query API calls."""

from __future__ import annotations

from app.graph.client import GraphHttpClient
from app.graph.errors import (
    DELTA_INVALID_ERROR_CODES,
    DeltaStateInvalidError,
    GraphApiError,
    GraphResponseInvalidError,
)
from app.graph.models import DeltaPage


def is_delta_state_invalid(error: GraphApiError) -> bool:
    if error.status_code == 410:
        return True
    code = (error.graph_error_code or "").lower()
    return code in DELTA_INVALID_ERROR_CODES


class GraphDeltaApi:
    def __init__(
        self, client: GraphHttpClient, *, page_size: int, select_fields: list[str]
    ) -> None:
        self._client = client
        self._page_size = page_size
        self._select = ",".join(select_fields)

    def baseline_url(self, mailbox_identifier: str, graph_folder_id: str) -> str:
        return self._client.build_url(
            f"users/{mailbox_identifier}/mailFolders/{graph_folder_id}/messages/delta"
        )

    async def fetch_page(self, url: str, *, is_baseline: bool) -> DeltaPage:
        headers = {"Prefer": f"odata.maxpagesize={self._page_size}"}
        params = {"$select": self._select} if is_baseline else None
        try:
            payload = await self._client.get_json(
                url, params=params, headers=headers, operation="delta_page"
            )
        except GraphApiError as exc:
            if is_delta_state_invalid(exc):
                raise DeltaStateInvalidError(
                    "Graph rejected the delta token; a rebaseline is required.",
                    details={
                        "graph_error_code": exc.graph_error_code,
                        "status_code": exc.status_code,
                    },
                ) from exc
            raise

        items = payload.get("value")
        next_link = payload.get("@odata.nextLink")
        delta_link = payload.get("@odata.deltaLink")
        if items is None or (next_link is None and delta_link is None):
            raise GraphResponseInvalidError(
                "Delta response is missing value[] or a continuation link."
            )
        return DeltaPage(items=list(items), next_link=next_link, delta_link=delta_link)
