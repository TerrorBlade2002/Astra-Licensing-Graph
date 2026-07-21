"""Durable processing of Graph change- and lifecycle-notification items.

The webhook handler validates, persists receipts, enqueues coalesced jobs,
and returns 202. It never calls Microsoft Graph.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.correlation import get_correlation_id
from app.core.metrics import (
    GRAPH_INVALID_CLIENT_STATE_TOTAL,
    GRAPH_LIFECYCLE_EVENTS_TOTAL,
    GRAPH_NOTIFICATIONS_DUPLICATE_TOTAL,
    GRAPH_NOTIFICATIONS_RECEIVED_TOTAL,
    GRAPH_UNKNOWN_SUBSCRIPTION_TOTAL,
)
from app.domain.enums import GraphSubscriptionStatus, NotificationReceiptStatus
from app.graph.models import GraphNotification, NotificationOutcome, WebhookProcessingSummary
from app.jobs.enums import JobType
from app.jobs.service import GraphJobService
from app.models import GraphNotificationReceipt, GraphSubscription
from app.models.mixins import utcnow
from app.webhooks.security import (
    notification_idempotency_key,
    payload_hash,
    verify_client_state,
)

logger = logging.getLogger(__name__)

LIFECYCLE_REAUTHORIZATION = "reauthorizationrequired"
LIFECYCLE_REMOVED = "subscriptionremoved"
LIFECYCLE_MISSED = "missed"


def _correlation_uuid() -> uuid.UUID | None:
    raw = get_correlation_id()
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


class GraphNotificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.jobs = GraphJobService(session, settings)

    async def process_collection(
        self, items: list[Any], *, is_lifecycle: bool
    ) -> WebhookProcessingSummary:
        summary = WebhookProcessingSummary()
        for raw in items:
            outcome = await self._process_item(raw, is_lifecycle=is_lifecycle)
            summary.outcomes.append(outcome)
            match outcome.status:
                case NotificationReceiptStatus.ACCEPTED.value:
                    summary.accepted += 1
                case NotificationReceiptStatus.DUPLICATE.value:
                    summary.duplicates += 1
                case NotificationReceiptStatus.INVALID_CLIENT_STATE.value:
                    summary.invalid_client_state += 1
                case NotificationReceiptStatus.UNKNOWN_SUBSCRIPTION.value:
                    summary.unknown_subscription += 1
                case _:
                    summary.malformed += 1
        await self.session.commit()
        return summary

    async def _process_item(self, raw: Any, *, is_lifecycle: bool) -> NotificationOutcome:
        if not isinstance(raw, dict):
            return NotificationOutcome(
                status=NotificationReceiptStatus.MALFORMED.value,
                detail="notification item is not an object",
            )
        try:
            notification = GraphNotification.model_validate(raw)
        except ValidationError:
            # Persist a MALFORMED receipt only when a subscription id exists.
            sub_id = raw.get("subscriptionId")
            if isinstance(sub_id, str) and sub_id:
                await self._persist_receipt(
                    subscription_row=None,
                    subscription_id=sub_id,
                    notification=None,
                    raw=raw,
                    status=NotificationReceiptStatus.MALFORMED,
                    client_state_valid=False,
                )
            return NotificationOutcome(
                status=NotificationReceiptStatus.MALFORMED.value,
                detail="schema validation failed",
            )

        expected_tenant = self.settings.graph_expected_tenant_id
        if expected_tenant and notification.tenant_id and notification.tenant_id != expected_tenant:
            await self._persist_receipt(
                subscription_row=None,
                subscription_id=notification.subscription_id,
                notification=notification,
                raw=raw,
                status=NotificationReceiptStatus.MALFORMED,
                client_state_valid=False,
                detail="tenant_mismatch",
            )
            return NotificationOutcome(
                status=NotificationReceiptStatus.MALFORMED.value, detail="tenant mismatch"
            )

        subscription = await self._locate_subscription(notification)
        if subscription is None:
            GRAPH_UNKNOWN_SUBSCRIPTION_TOTAL.inc()
            receipt = await self._persist_receipt(
                subscription_row=None,
                subscription_id=notification.subscription_id,
                notification=notification,
                raw=raw,
                status=NotificationReceiptStatus.UNKNOWN_SUBSCRIPTION,
                client_state_valid=False,
            )
            return NotificationOutcome(
                status=NotificationReceiptStatus.UNKNOWN_SUBSCRIPTION.value,
                receipt_id=str(receipt.id) if receipt else None,
            )

        if not verify_client_state(notification.client_state, subscription.client_state_hash):
            GRAPH_INVALID_CLIENT_STATE_TOTAL.inc()
            logger.warning(
                "Notification failed clientState validation",
                extra={
                    "extra_fields": {
                        "subscription_db_id": str(subscription.id),
                        "security_event": "invalid_client_state",
                    }
                },
            )
            receipt = await self._persist_receipt(
                subscription_row=subscription,
                subscription_id=notification.subscription_id,
                notification=notification,
                raw=raw,
                status=NotificationReceiptStatus.INVALID_CLIENT_STATE,
                client_state_valid=False,
            )
            return NotificationOutcome(
                status=NotificationReceiptStatus.INVALID_CLIENT_STATE.value,
                receipt_id=str(receipt.id) if receipt else None,
            )

        receipt = await self._persist_receipt(
            subscription_row=subscription,
            subscription_id=notification.subscription_id,
            notification=notification,
            raw=raw,
            status=NotificationReceiptStatus.ACCEPTED,
            client_state_valid=True,
        )
        if receipt is None:
            GRAPH_NOTIFICATIONS_DUPLICATE_TOTAL.inc()
            return NotificationOutcome(status=NotificationReceiptStatus.DUPLICATE.value)

        GRAPH_NOTIFICATIONS_RECEIVED_TOTAL.inc()
        now = utcnow()
        if is_lifecycle or notification.lifecycle_event:
            subscription.last_lifecycle_event_at = now
            job_id = await self._handle_lifecycle(subscription, notification, receipt)
        else:
            subscription.last_notification_at = now
            job_id = await self._enqueue_sync(
                subscription,
                reason=f"NOTIFICATION:{notification.change_type or 'unknown'}",
                receipt=receipt,
            )
        return NotificationOutcome(
            status=NotificationReceiptStatus.ACCEPTED.value,
            receipt_id=str(receipt.id),
            job_id=job_id,
        )

    # ------------------------------------------------------------- internals

    async def _locate_subscription(
        self, notification: GraphNotification
    ) -> GraphSubscription | None:
        row = await self.session.scalar(
            select(GraphSubscription).where(
                GraphSubscription.graph_subscription_id == notification.subscription_id
            )
        )
        if row is not None:
            return row
        # Creation race: Graph validates and may notify before the local row
        # holds the returned subscription ID. Match CREATING rows by
        # client-state hash + resource.
        if not notification.client_state:
            return None
        creating_rows = (
            await self.session.scalars(
                select(GraphSubscription).where(
                    GraphSubscription.status == GraphSubscriptionStatus.CREATING.value
                )
            )
        ).all()
        matches = [
            row
            for row in creating_rows
            if verify_client_state(notification.client_state, row.client_state_hash)
            and (notification.resource is None or row.resource == notification.resource)
        ]
        if len(matches) == 1:
            match = matches[0]
            if match.graph_subscription_id is None:
                match.graph_subscription_id = notification.subscription_id
            return match
        return None

    async def _persist_receipt(
        self,
        *,
        subscription_row: GraphSubscription | None,
        subscription_id: str,
        notification: GraphNotification | None,
        raw: dict[str, Any],
        status: NotificationReceiptStatus,
        client_state_valid: bool,
        detail: str | None = None,
    ) -> GraphNotificationReceipt | None:
        """Insert a receipt; None when the idempotency key already exists."""
        idem = notification_idempotency_key(
            subscription_id=subscription_id,
            notification_id=notification.notification_id if notification else None,
            tenant_id=notification.tenant_id if notification else None,
            resource=notification.resource if notification else None,
            change_type=notification.change_type if notification else None,
            lifecycle_event=notification.lifecycle_event if notification else None,
            subscription_expiration=(
                notification.subscription_expiration if notification else None
            ),
        )
        existing = await self.session.scalar(
            select(GraphNotificationReceipt).where(GraphNotificationReceipt.idempotency_key == idem)
        )
        if existing is not None:
            return None

        receipt = GraphNotificationReceipt(
            id=uuid.uuid4(),
            graph_subscription_db_id=subscription_row.id if subscription_row else None,
            graph_subscription_id=subscription_id,
            graph_notification_id=notification.notification_id if notification else None,
            tenant_id=notification.tenant_id if notification else None,
            change_type=notification.change_type if notification else None,
            lifecycle_event=notification.lifecycle_event if notification else None,
            resource=notification.resource if notification else None,
            payload_hash=payload_hash(raw),
            idempotency_key=idem,
            client_state_valid=client_state_valid,
            processing_status=status.value,
            correlation_id=_correlation_uuid(),
            received_at=utcnow(),
            receipt_metadata={"detail": detail} if detail else {},
        )
        self.session.add(receipt)
        await self.session.flush()
        return receipt

    async def _enqueue_sync(
        self, subscription: GraphSubscription, *, reason: str, receipt: GraphNotificationReceipt
    ) -> str | None:
        result = await self.jobs.enqueue_sync_folder(
            mailbox_id=subscription.mailbox_id,
            folder_id=subscription.folder_id,
            reason=reason,
            idempotency_key=f"sync-receipt:{receipt.id}",
        )
        return str(result.job.id)

    async def _handle_lifecycle(
        self,
        subscription: GraphSubscription,
        notification: GraphNotification,
        receipt: GraphNotificationReceipt,
    ) -> str | None:
        event = (notification.lifecycle_event or "").lower()
        GRAPH_LIFECYCLE_EVENTS_TOTAL.labels(event=event or "unknown").inc()
        now = utcnow()

        if event == LIFECYCLE_REAUTHORIZATION:
            subscription.status = GraphSubscriptionStatus.REAUTHORIZATION_REQUIRED.value
            subscription.reauthorization_required_at = now
            result = await self.jobs.enqueue_subscription_maintenance(
                job_type=JobType.RENEW_SUBSCRIPTION,
                mailbox_id=subscription.mailbox_id,
                folder_id=subscription.folder_id,
                reason="LIFECYCLE_REAUTHORIZATION_REQUIRED",
                idempotency_key=f"renew-receipt:{receipt.id}",
            )
            await self.jobs.enqueue_sync_folder(
                mailbox_id=subscription.mailbox_id,
                folder_id=subscription.folder_id,
                reason="LIFECYCLE_REAUTHORIZATION_SAFEGUARD",
                idempotency_key=f"sync-receipt:{receipt.id}",
            )
            return str(result.job.id)

        if event == LIFECYCLE_REMOVED:
            subscription.status = GraphSubscriptionStatus.REMOVED.value
            subscription.removed_at = now
            result = await self.jobs.enqueue_subscription_maintenance(
                job_type=JobType.RECREATE_SUBSCRIPTION,
                mailbox_id=subscription.mailbox_id,
                folder_id=subscription.folder_id,
                reason="LIFECYCLE_SUBSCRIPTION_REMOVED",
                idempotency_key=f"recreate-receipt:{receipt.id}",
            )
            return str(result.job.id)

        if event == LIFECYCLE_MISSED:
            result = await self.jobs.enqueue_sync_folder(
                mailbox_id=subscription.mailbox_id,
                folder_id=subscription.folder_id,
                reason="LIFECYCLE_MISSED",
                idempotency_key=f"sync-receipt:{receipt.id}",
            )
            return str(result.job.id)

        logger.info(
            "Unhandled lifecycle event recorded",
            extra={"extra_fields": {"lifecycle_event": event or "unknown"}},
        )
        return None
