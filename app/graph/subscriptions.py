"""Graph subscription API calls (thin wrapper over GraphHttpClient)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.graph.client import GraphHttpClient


def subscription_expiration(lifetime_minutes: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(minutes=lifetime_minutes)


def format_graph_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class GraphSubscriptionApi:
    def __init__(self, client: GraphHttpClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        resource: str,
        change_types: str,
        notification_url: str,
        lifecycle_notification_url: str,
        expiration: datetime,
        client_state: str,
    ) -> dict[str, Any]:
        body = {
            "changeType": change_types,
            "notificationUrl": notification_url,
            "lifecycleNotificationUrl": lifecycle_notification_url,
            "resource": resource,
            "expirationDateTime": format_graph_datetime(expiration),
            "clientState": client_state,
            "latestSupportedTlsVersion": "v1_2",
        }
        return await self._client.post_json(
            self._client.build_url("subscriptions"), body, operation="subscription_create"
        )

    async def renew(self, graph_subscription_id: str, expiration: datetime) -> dict[str, Any]:
        return await self._client.patch_json(
            self._client.build_url(f"subscriptions/{graph_subscription_id}"),
            {"expirationDateTime": format_graph_datetime(expiration)},
            operation="subscription_renew",
        )

    async def delete(self, graph_subscription_id: str) -> None:
        await self._client.delete(
            self._client.build_url(f"subscriptions/{graph_subscription_id}"),
            operation="subscription_delete",
        )

    async def list_all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = self._client.build_url("subscriptions")
        while url:
            page = await self._client.get_json(url, operation="subscription_list")
            items.extend(page.get("value") or [])
            next_link = page.get("@odata.nextLink")
            url = self._client.validate_continuation_url(next_link) if next_link else ""
        return items
