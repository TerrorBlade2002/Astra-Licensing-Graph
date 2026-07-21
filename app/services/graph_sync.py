"""Folder delta synchronization (the authoritative change source).

Checkpoint rules:
- pages are committed one at a time (no open transaction during HTTP calls),
- the saved deltaLink only advances after the whole round succeeds,
- replayed pages are harmless because every upsert is idempotent,
- an invalid sync token triggers a controlled rebaseline, never data loss.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.core.metrics import (
    GRAPH_DELTA_CHANGES_TOTAL,
    GRAPH_DELTA_PAGES_TOTAL,
    GRAPH_DELTA_REBASELINE_TOTAL,
    GRAPH_SYNC_DURATION_SECONDS,
)
from app.domain.enums import FolderMembership, ProcessingState
from app.graph.delta import GraphDeltaApi
from app.graph.errors import DeltaStateInvalidError
from app.graph.models import DeltaRoundResult
from app.graph.urls import fingerprint_url, validate_graph_url
from app.jobs.leasing import acquire_sync_lease, release_sync_lease
from app.jobs.service import GraphJobService
from app.models import (
    AuditEvent,
    Email,
    EmailProcessingEvent,
    Mailbox,
    MailboxFolder,
    MailboxSyncState,
    OutboxEvent,
)
from app.models.mixins import utcnow
from app.services.graph_subscriptions import mailbox_identifier

logger = logging.getLogger(__name__)


def parse_graph_dt(value: Any) -> Any:
    from app.services.prototype_import import parse_dt

    return parse_dt(value)


class FolderDeltaSyncService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        delta_api: GraphDeltaApi,
        *,
        worker_id: str,
    ) -> None:
        self.session = session
        self.settings = settings
        self.delta_api = delta_api
        self.worker_id = worker_id
        self.jobs = GraphJobService(session, settings)

    async def sync_folder(
        self, mailbox_id: uuid.UUID, folder_id: uuid.UUID, *, job_id: uuid.UUID | None = None
    ) -> DeltaRoundResult:
        mailbox = await self.session.get(Mailbox, mailbox_id)
        folder = await self.session.get(MailboxFolder, folder_id)
        if mailbox is None or folder is None:
            raise DomainError("Mailbox or folder not found for delta sync.")

        state = await self._get_or_create_state(mailbox_id, folder_id)
        acquired = await acquire_sync_lease(
            self.session,
            state.id,
            owner=self.worker_id,
            lease_seconds=self.settings.graph_job_lease_seconds,
        )
        if not acquired:
            raise DomainError(
                "Folder sync lease is held by another worker.",
                details={"folder_id": str(folder_id)},
            )

        started = time.perf_counter()
        try:
            result = await self._run_round(mailbox, folder, state, job_id=job_id)
            GRAPH_SYNC_DURATION_SECONDS.observe(time.perf_counter() - started)
            return result
        except DeltaStateInvalidError:
            await self._handle_invalid_delta_state(mailbox, folder, state)
            GRAPH_DELTA_REBASELINE_TOTAL.inc()
            result = DeltaRoundResult(rebaselined=True)
            return result
        except Exception as exc:
            state.last_error_code = getattr(exc, "code", type(exc).__name__)[:100]
            state.last_error_message = str(getattr(exc, "safe_message", None) or exc)[:500]
            if job_id is not None:
                state.last_failed_job_id = job_id
            await self.session.commit()
            raise
        finally:
            await release_sync_lease(self.session, state.id, owner=self.worker_id)

    # ------------------------------------------------------------------ round

    async def _run_round(
        self,
        mailbox: Mailbox,
        folder: MailboxFolder,
        state: MailboxSyncState,
        *,
        job_id: uuid.UUID | None,
    ) -> DeltaRoundResult:
        result = DeltaRoundResult()
        is_baseline = state.delta_link is None or state.needs_rebaseline
        if is_baseline:
            url = self.delta_api.baseline_url(mailbox_identifier(mailbox), folder.graph_folder_id)
        else:
            assert state.delta_link is not None
            url = validate_graph_url(
                state.delta_link, allowed_host=self.settings.graph_allowed_host
            ).url

        state.last_started_at = utcnow()
        await self.session.commit()

        new_delta_link: str | None = None
        first_page = True
        while True:
            # HTTP call happens outside any open transaction.
            page = await self.delta_api.fetch_page(url, is_baseline=is_baseline and first_page)
            first_page = False
            GRAPH_DELTA_PAGES_TOTAL.inc()
            result.pages += 1

            await self._apply_page(mailbox, folder, page.items, result)
            await self.session.commit()

            if page.delta_link:
                new_delta_link = page.delta_link
                break
            assert page.next_link is not None
            url = validate_graph_url(
                page.next_link, allowed_host=self.settings.graph_allowed_host
            ).url

        # The checkpoint advances only after every page committed successfully.
        validated = validate_graph_url(
            new_delta_link, allowed_host=self.settings.graph_allowed_host
        )
        state.delta_link = validated.url
        state.last_delta_url_fingerprint = validated.fingerprint
        state.needs_rebaseline = False
        state.last_completed_at = utcnow()
        state.last_page_count = result.pages
        state.last_change_count = result.changes
        state.last_error_code = None
        state.last_error_message = None
        if job_id is not None:
            state.last_successful_job_id = job_id
        await self.session.commit()

        logger.info(
            "Delta sync round completed",
            extra={
                "extra_fields": {
                    "mailbox_id": str(mailbox.id),
                    "folder_id": str(folder.id),
                    "pages": result.pages,
                    "created": result.created,
                    "updated": result.updated,
                    "removed": result.removed,
                    "delta_url_fingerprint": validated.fingerprint,
                }
            },
        )
        return result

    async def _apply_page(
        self,
        mailbox: Mailbox,
        folder: MailboxFolder,
        items: list[dict[str, Any]],
        result: DeltaRoundResult,
    ) -> None:
        for item in items:
            if "@removed" in item:
                GRAPH_DELTA_CHANGES_TOTAL.labels(kind="removed").inc()
                await self._apply_removal(mailbox, folder, item)
                result.removed += 1
                continue
            created = await self._upsert_message(mailbox, folder, item, result)
            if created:
                GRAPH_DELTA_CHANGES_TOTAL.labels(kind="created").inc()
                result.created += 1
            else:
                GRAPH_DELTA_CHANGES_TOTAL.labels(kind="updated").inc()
                result.updated += 1

    async def _upsert_message(
        self,
        mailbox: Mailbox,
        folder: MailboxFolder,
        item: dict[str, Any],
        result: DeltaRoundResult,
    ) -> bool:
        graph_message_id = item.get("id")
        if not graph_message_id:
            logger.warning("Delta item without id skipped")
            return False

        email = await self.session.scalar(
            select(Email).where(
                Email.mailbox_id == mailbox.id,
                Email.graph_message_id == graph_message_id,
            )
        )
        sender = ((item.get("from") or {}).get("emailAddress")) or {}
        now = utcnow()

        if email is not None:
            # Existing message: refresh mutable Graph metadata only. The
            # processing state machine is never reset by a delta update.
            email.subject = item.get("subject", email.subject)
            email.sender_name = sender.get("name", email.sender_name)
            if sender.get("address"):
                email.sender_email = str(sender["address"]).lower()
            email.is_read = item.get("isRead", email.is_read)
            email.has_attachments = bool(item.get("hasAttachments", email.has_attachments))
            email.body_preview = item.get("bodyPreview", email.body_preview)
            email.current_graph_folder_id = item.get(
                "parentFolderId", email.current_graph_folder_id
            )
            email.last_graph_modified_at = parse_graph_dt(item.get("lastModifiedDateTime"))
            email.graph_etag = item.get("@odata.etag", email.graph_etag)
            email.synced_folder_membership = FolderMembership.PRESENT.value
            email.removed_from_synced_folder_at = None
            return False

        email = Email(
            id=uuid.uuid4(),
            mailbox_id=mailbox.id,
            graph_message_id=graph_message_id,
            internet_message_id=item.get("internetMessageId"),
            conversation_id=item.get("conversationId"),
            current_graph_folder_id=item.get("parentFolderId") or folder.graph_folder_id,
            subject=item.get("subject"),
            sender_name=sender.get("name"),
            sender_email=(str(sender.get("address")).lower() if sender.get("address") else None),
            received_at=parse_graph_dt(item.get("receivedDateTime")),
            body_preview=item.get("bodyPreview"),
            has_attachments=bool(item.get("hasAttachments")),
            is_read=item.get("isRead"),
            processing_state=ProcessingState.DISCOVERED.value,
            synced_folder_membership=FolderMembership.PRESENT.value,
            last_graph_modified_at=parse_graph_dt(item.get("lastModifiedDateTime")),
            graph_etag=item.get("@odata.etag"),
            discovered_at=now,
        )
        self.session.add(email)
        await self.session.flush()

        self.session.add(
            EmailProcessingEvent(
                email_id=email.id,
                from_state=None,
                to_state=ProcessingState.DISCOVERED.value,
                event_type="delta_discovered",
                note="Message reported by folder delta synchronization.",
                event_metadata={"folder_id": str(folder.id)},
                occurred_at=now,
            )
        )
        self.session.add(
            AuditEvent(
                actor_type="SYSTEM",
                actor_id=self.worker_id,
                entity_type="email",
                entity_id=str(email.id),
                action="email_discovered",
                after_data={"processing_state": ProcessingState.DISCOVERED.value},
                occurred_at=now,
            )
        )
        self.session.add(
            OutboxEvent(
                aggregate_type="email",
                aggregate_id=str(email.id),
                event_type="email.discovered",
                payload={"email_id": str(email.id), "mailbox_id": str(mailbox.id)},
                idempotency_key=f"email-discovered:{email.id}",
                status="PENDING",
                available_at=now,
            )
        )
        enqueue = await self.jobs.enqueue_ingest_email(
            mailbox_id=mailbox.id,
            email_id=email.id,
            reason="DELTA_DISCOVERED",
            idempotency_key=f"ingest-discovered:{email.id}",
        )
        if enqueue.created:
            result.ingest_jobs_enqueued += 1
        email.ingestion_job_id = enqueue.job.id
        return True

    async def _apply_removal(
        self, mailbox: Mailbox, folder: MailboxFolder, item: dict[str, Any]
    ) -> None:
        graph_message_id = item.get("id")
        if not graph_message_id:
            return
        email = await self.session.scalar(
            select(Email).where(
                Email.mailbox_id == mailbox.id,
                Email.graph_message_id == graph_message_id,
            )
        )
        if email is None:
            return
        now = utcnow()
        email.synced_folder_membership = FolderMembership.REMOVED.value
        email.removed_from_synced_folder_at = now
        if email.current_graph_folder_id == folder.graph_folder_id:
            email.current_graph_folder_id = None
        reason = (item.get("@removed") or {}).get("reason")
        # Non-transition event: the workflow state is deliberately untouched,
        # and removal may mean deletion or a move out of the synced folder.
        self.session.add(
            EmailProcessingEvent(
                email_id=email.id,
                from_state=email.processing_state,
                to_state=email.processing_state,
                event_type="folder_removed",
                note=f"Delta reported removal from synced folder (reason: {reason or 'unknown'}).",
                event_metadata={"folder_id": str(folder.id), "removal_reason": reason},
                occurred_at=now,
            )
        )

    # -------------------------------------------------------------- rebaseline

    async def _handle_invalid_delta_state(
        self, mailbox: Mailbox, folder: MailboxFolder, state: MailboxSyncState
    ) -> None:
        fingerprint = fingerprint_url(state.delta_link) if state.delta_link else None
        state.needs_rebaseline = True
        state.delta_link = None
        state.last_delta_url_fingerprint = fingerprint
        state.last_error_code = "delta_state_invalid"
        state.last_error_message = "Graph rejected the sync token; rebaseline scheduled."
        self.session.add(
            AuditEvent(
                actor_type="SYSTEM",
                actor_id=self.worker_id,
                entity_type="mailbox_sync_state",
                entity_id=str(state.id),
                action="delta_rebaseline_scheduled",
                after_data={"invalid_delta_fingerprint": fingerprint},
                occurred_at=utcnow(),
            )
        )
        await self.jobs.enqueue_sync_folder(
            mailbox_id=mailbox.id,
            folder_id=folder.id,
            reason="REBASELINE_AFTER_INVALID_DELTA",
            idempotency_key=f"rebaseline:{state.id}:{utcnow().isoformat()}",
        )
        await self.session.commit()
        logger.warning(
            "Delta state invalid; rebaseline scheduled",
            extra={
                "extra_fields": {
                    "sync_state_id": str(state.id),
                    "invalid_delta_fingerprint": fingerprint,
                }
            },
        )

    async def _get_or_create_state(
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
