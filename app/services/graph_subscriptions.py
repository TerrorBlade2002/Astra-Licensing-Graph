"""Graph subscription lifecycle management."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.core.metrics import GRAPH_SUBSCRIPTION_RENEWAL_FAILURES_TOTAL
from app.domain.enums import ACTIVE_SUBSCRIPTION_STATUSES, GraphSubscriptionStatus
from app.graph.errors import GraphApiError
from app.graph.subscriptions import GraphSubscriptionApi, subscription_expiration
from app.models import AuditEvent, GraphSubscription, Mailbox, MailboxFolder, MailboxSyncState
from app.models.mixins import utcnow
from app.webhooks.security import generate_client_state, hash_client_state

logger = logging.getLogger(__name__)

_STALE_CREATING_AGE = timedelta(minutes=10)


class SubscriptionConflictError(DomainError):
    code = "subscription_conflict"
    http_status = 409


@dataclass
class ReconciliationReport:
    remote_only: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "remote_only": self.remote_only,
            "local_only": self.local_only,
            "matched": self.matched,
            "adopted": self.adopted,
            "deleted_remote": self.deleted_remote,
        }


def mailbox_identifier(mailbox: Mailbox) -> str:
    return mailbox.graph_user_id or mailbox.address


def build_resource(mailbox: Mailbox, folder: MailboxFolder) -> str:
    return f"users/{mailbox_identifier(mailbox)}/mailFolders/{folder.graph_folder_id}/messages"


class GraphSubscriptionService:
    def __init__(
        self, session: AsyncSession, settings: Settings, api: GraphSubscriptionApi
    ) -> None:
        self.session = session
        self.settings = settings
        self.api = api

    # ------------------------------------------------------------------ ensure

    async def ensure_subscription(
        self, mailbox_id: uuid.UUID, folder_id: uuid.UUID, *, actor_id: str = "scheduler"
    ) -> GraphSubscription:
        """Idempotent: create, renew, or no-op depending on current state."""
        mailbox = await self.session.get(Mailbox, mailbox_id)
        folder = await self.session.get(MailboxFolder, folder_id)
        if mailbox is None or folder is None:
            raise DomainError("Mailbox or folder not found for subscription ensure.")

        rows = (
            await self.session.scalars(
                select(GraphSubscription).where(
                    GraphSubscription.mailbox_id == mailbox_id,
                    GraphSubscription.folder_id == folder_id,
                    GraphSubscription.status.in_([s.value for s in ACTIVE_SUBSCRIPTION_STATUSES]),
                )
            )
        ).all()

        if len(rows) > 1:
            raise SubscriptionConflictError(
                "Multiple active subscription records exist; human review required.",
                details={"subscription_ids": [str(r.id) for r in rows]},
            )

        now = utcnow()
        renewal_window = timedelta(minutes=self.settings.graph_subscription_renewal_window_minutes)

        if not rows:
            return await self._create(mailbox, folder, actor_id=actor_id)

        row = rows[0]
        status = GraphSubscriptionStatus(row.status)

        if status == GraphSubscriptionStatus.CREATING:
            if now - row.created_at < _STALE_CREATING_AGE:
                return row  # a creation is already in flight
            row.status = GraphSubscriptionStatus.ERROR.value
            row.last_error_code = "stale_creating"
            row.last_error_message = "Creation never completed; replacing subscription."
            await self.session.commit()
            return await self._create(mailbox, folder, actor_id=actor_id)

        if status == GraphSubscriptionStatus.ACTIVE:
            if row.expiration_at is not None and row.expiration_at - now > renewal_window:
                return row  # sufficient lifetime remains
            return await self._renew(row, mailbox, folder, actor_id=actor_id)

        # RENEWAL_REQUIRED or REAUTHORIZATION_REQUIRED
        return await self._renew(row, mailbox, folder, actor_id=actor_id)

    # ------------------------------------------------------------------ create

    async def _create(
        self, mailbox: Mailbox, folder: MailboxFolder, *, actor_id: str
    ) -> GraphSubscription:
        client_state = generate_client_state()
        row = GraphSubscription(
            id=uuid.uuid4(),
            mailbox_id=mailbox.id,
            folder_id=folder.id,
            resource=build_resource(mailbox, folder),
            change_types=self.settings.graph_subscription_change_types,
            notification_url=self.settings.notification_url,
            lifecycle_notification_url=self.settings.lifecycle_url,
            client_state_hash=hash_client_state(client_state),
            status=GraphSubscriptionStatus.CREATING.value,
        )
        self.session.add(row)
        # Commit before calling Graph: the validation webhook (and even a first
        # notification) can arrive while the create call is still in flight.
        await self.session.commit()

        expiration = subscription_expiration(self.settings.graph_subscription_lifetime_minutes)
        try:
            payload = await self.api.create(
                resource=row.resource,
                change_types=row.change_types,
                notification_url=row.notification_url,
                lifecycle_notification_url=row.lifecycle_notification_url,
                expiration=expiration,
                client_state=client_state,
            )
        except Exception as exc:
            row.status = GraphSubscriptionStatus.ERROR.value
            row.last_error_code = str(
                getattr(exc, "graph_error_code", None)
                or getattr(exc, "code", "subscription_create_failed")
            )
            row.last_error_message = str(getattr(exc, "safe_message", None) or exc)[:500]
            await self.session.commit()
            raise
        finally:
            del client_state  # plaintext never outlives the creation call

        graph_id = payload.get("id")
        if row.graph_subscription_id is None:
            row.graph_subscription_id = graph_id
        row.expiration_at = self._parse_expiration(payload.get("expirationDateTime"), expiration)
        row.status = GraphSubscriptionStatus.ACTIVE.value
        row.last_error_code = None
        row.last_error_message = None
        self._audit(row, "subscription_created", actor_id)
        await self.session.commit()
        logger.info(
            "Graph subscription created",
            extra={"extra_fields": {"subscription_db_id": str(row.id)}},
        )
        return row

    # ------------------------------------------------------------------- renew

    async def _renew(
        self, row: GraphSubscription, mailbox: Mailbox, folder: MailboxFolder, *, actor_id: str
    ) -> GraphSubscription:
        if row.graph_subscription_id is None:
            return await self.recreate(row, actor_id=actor_id)
        expiration = subscription_expiration(self.settings.graph_subscription_lifetime_minutes)
        try:
            payload = await self.api.renew(row.graph_subscription_id, expiration)
        except GraphApiError as exc:
            GRAPH_SUBSCRIPTION_RENEWAL_FAILURES_TOTAL.inc()
            if exc.status_code == 404:
                # Graph no longer knows this subscription: replace it.
                return await self.recreate(row, actor_id=actor_id)
            row.status = GraphSubscriptionStatus.RENEWAL_REQUIRED.value
            row.last_error_code = exc.graph_error_code or str(exc.status_code)
            row.last_error_message = exc.safe_message
            await self.session.commit()
            raise

        row.expiration_at = self._parse_expiration(payload.get("expirationDateTime"), expiration)
        row.last_renewed_at = utcnow()
        row.status = GraphSubscriptionStatus.ACTIVE.value
        row.reauthorization_required_at = None
        row.last_error_code = None
        row.last_error_message = None
        self._audit(row, "subscription_renewed", actor_id)
        await self.session.commit()
        return row

    async def recreate(self, row: GraphSubscription, *, actor_id: str) -> GraphSubscription:
        mailbox = await self.session.get(Mailbox, row.mailbox_id)
        folder = await self.session.get(MailboxFolder, row.folder_id)
        if mailbox is None or folder is None:
            raise DomainError("Mailbox or folder vanished during subscription recreate.")
        if GraphSubscriptionStatus(row.status) in ACTIVE_SUBSCRIPTION_STATUSES:
            row.status = GraphSubscriptionStatus.REMOVED.value
            row.removed_at = utcnow()
            await self.session.commit()
        return await self._create(mailbox, folder, actor_id=actor_id)

    # ---------------------------------------------------------------- helpers

    def _parse_expiration(self, raw: Any, fallback: datetime) -> datetime:
        if isinstance(raw, str):
            try:
                text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
                parsed = datetime.fromisoformat(text)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
        return fallback

    def _audit(self, row: GraphSubscription, action: str, actor_id: str) -> None:
        self.session.add(
            AuditEvent(
                actor_type="SYSTEM",
                actor_id=actor_id,
                entity_type="graph_subscription",
                entity_id=str(row.id),
                action=action,
                after_data={
                    "status": row.status,
                    "expiration_at": row.expiration_at.isoformat() if row.expiration_at else None,
                },
                occurred_at=utcnow(),
            )
        )

    async def ensure_sync_state(
        self, mailbox_id: uuid.UUID, folder_id: uuid.UUID
    ) -> MailboxSyncState:
        state = await self.session.scalar(
            select(MailboxSyncState).where(
                MailboxSyncState.mailbox_id == mailbox_id,
                MailboxSyncState.folder_id == folder_id,
            )
        )
        if state is None:
            state = MailboxSyncState(id=uuid.uuid4(), mailbox_id=mailbox_id, folder_id=folder_id)
            self.session.add(state)
            await self.session.commit()
        return state

    # ------------------------------------------------------------- reconcile

    async def reconcile(
        self, mailbox_id: uuid.UUID, *, dry_run: bool, delete_unknown_remote: bool = False
    ) -> ReconciliationReport:
        report = ReconciliationReport()
        remote = await self.api.list_all()
        local_rows = (
            await self.session.scalars(
                select(GraphSubscription).where(
                    GraphSubscription.mailbox_id == mailbox_id,
                    GraphSubscription.status.in_([s.value for s in ACTIVE_SUBSCRIPTION_STATUSES]),
                )
            )
        ).all()
        local_by_graph_id = {
            r.graph_subscription_id: r for r in local_rows if r.graph_subscription_id
        }
        # Only consider remote subscriptions that point at our webhook.
        ours = [
            s
            for s in remote
            if str(s.get("notificationUrl", "")).startswith(
                self.settings.public_base_url.rstrip("/")
            )
        ]
        remote_ids = {str(s.get("id")) for s in ours}

        for sub in ours:
            sub_id = str(sub.get("id"))
            if sub_id in local_by_graph_id:
                report.matched.append(sub_id)
                continue
            # Adopt only when exactly one local active row matches the resource
            # and has no Graph ID yet (creation race remnants).
            candidates = [
                r
                for r in local_rows
                if r.graph_subscription_id is None and r.resource == sub.get("resource")
            ]
            if len(candidates) == 1:
                report.adopted.append(sub_id)
                if not dry_run:
                    candidates[0].graph_subscription_id = sub_id
                    candidates[0].status = GraphSubscriptionStatus.ACTIVE.value
                continue
            report.remote_only.append(sub_id)
            if delete_unknown_remote and not dry_run:
                await self.api.delete(sub_id)
                report.deleted_remote.append(sub_id)

        for row in local_rows:
            if row.graph_subscription_id and row.graph_subscription_id not in remote_ids:
                report.local_only.append(str(row.id))
                if not dry_run:
                    row.status = GraphSubscriptionStatus.EXPIRED.value

        if not dry_run:
            await self.session.commit()
        return report
