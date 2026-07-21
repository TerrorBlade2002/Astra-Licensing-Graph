"""Typed views over Graph payloads used by services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class GraphSubscriptionInfo:
    subscription_id: str
    resource: str | None
    expiration_date_time: str | None
    change_type: str | None
    notification_url: str | None


@dataclass(frozen=True)
class DeltaPage:
    items: list[dict[str, Any]]
    next_link: str | None
    delta_link: str | None


@dataclass
class DeltaRoundResult:
    pages: int = 0
    created: int = 0
    updated: int = 0
    removed: int = 0
    ingest_jobs_enqueued: int = 0
    rebaselined: bool = False

    @property
    def changes(self) -> int:
        return self.created + self.updated + self.removed


class GraphNotification(BaseModel):
    """One entry of a change- or lifecycle-notification collection."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    subscription_id: str = Field(alias="subscriptionId")
    notification_id: str | None = Field(default=None, alias="id")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    client_state: str | None = Field(default=None, alias="clientState")
    change_type: str | None = Field(default=None, alias="changeType")
    lifecycle_event: str | None = Field(default=None, alias="lifecycleEvent")
    resource: str | None = None
    subscription_expiration: str | None = Field(
        default=None, alias="subscriptionExpirationDateTime"
    )


@dataclass
class NotificationOutcome:
    status: str
    receipt_id: str | None = None
    job_id: str | None = None
    detail: str | None = None


@dataclass
class WebhookProcessingSummary:
    accepted: int = 0
    duplicates: int = 0
    invalid_client_state: int = 0
    unknown_subscription: int = 0
    malformed: int = 0
    outcomes: list[NotificationOutcome] = field(default_factory=list)
