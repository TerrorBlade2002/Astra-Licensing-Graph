"""Importer for the PowerShell prototype's JSON files.

The prototype persisted its state with PowerShell's ConvertTo-Json, which
produces several wrapper shapes for "a list of records":

* a single object                       {...}
* an array                              [{...}]
* a nested array                        [[{...}]]
* a wrapper object                      {"value": [...]} / {"records": [...]}

``flatten_records`` normalizes all of them. Each prototype record is imported
in its own transaction; a malformed record is reported and rolled back without
touching other records.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import PrototypeImportError
from app.domain.enums import ActorType, DraftStatus, ProcessingState, TaskStatus
from app.models import (
    AuditEvent,
    Classification,
    ClassificationReview,
    Email,
    EmailAttachment,
    EmailProcessingEvent,
    EmailRecipient,
    LicensingTask,
    MailboxFolder,
    OutboundDraft,
    TaskRequestedItem,
)
from app.models.mixins import utcnow
from app.repositories.mailboxes import MailboxRepository

logger = logging.getLogger(__name__)

_WRAPPER_KEYS = ("records", "value", "items")


def flatten_records(payload: Any) -> list[dict[str, Any]]:
    """Normalize the prototype's JSON wrapper shapes into a flat list of dicts."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in _WRAPPER_KEYS:
            if key in payload and isinstance(payload[key], list):
                return flatten_records(payload[key])
        return [payload]
    if isinstance(payload, list):
        flat: list[dict[str, Any]] = []
        for element in payload:
            flat.extend(flatten_records(element))
        return flat
    raise PrototypeImportError(f"Unsupported JSON shape: {type(payload).__name__}")


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # PowerShell emits 7-digit fractional seconds; Python accepts at most 6.
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        if "." in text:
            head, _, tail = text.partition(".")
            frac = ""
            offset = ""
            for i, ch in enumerate(tail):
                if ch.isdigit():
                    frac += ch
                else:
                    offset = tail[i:]
                    break
            parsed = datetime.fromisoformat(f"{head}.{frac[:6]}{offset}")
        else:
            raise
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value)[:10])


def to_file_uri(windows_path: str | None) -> str | None:
    if not windows_path:
        return None
    return PureWindowsPath(windows_path).as_uri()


def load_json(path: Path) -> Any:
    # utf-8-sig: PowerShell writes a BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


@dataclass
class RecordResult:
    record_key: str
    status: str  # inserted | updated | skipped | error
    reason: str | None = None


@dataclass
class ImportReport:
    root: str
    mailbox: str
    dry_run: bool
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    records: list[RecordResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "mailbox": self.mailbox,
            "dry_run": self.dry_run,
            "counts": {
                "inserted": self.inserted,
                "updated": self.updated,
                "skipped": self.skipped,
                "errors": self.errors,
            },
            "records": [
                {"record_key": r.record_key, "status": r.status, "reason": r.reason}
                for r in self.records
            ],
        }


class PrototypeImporter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        root: Path,
        mailbox_address: str,
        *,
        dry_run: bool = False,
        actor_id: str = "prototype-import-cli",
    ) -> None:
        self.session_factory = session_factory
        # file:// URIs require absolute paths.
        self.root = root.resolve()
        self.mailbox_address = mailbox_address.strip().lower()
        self.dry_run = dry_run
        self.actor_id = actor_id
        self.report = ImportReport(root=str(root), mailbox=self.mailbox_address, dry_run=dry_run)

    # ------------------------------------------------------------------ paths

    @property
    def state_file(self) -> Path:
        return self.root / "processing" / "state" / "email_processing_state.json"

    def record_dir(self, kind: str, record_key: str) -> Path:
        return self.root / "processing" / kind / record_key

    # ------------------------------------------------------------------ entry

    async def run(self) -> ImportReport:
        if not self.state_file.exists():
            raise PrototypeImportError(
                f"State file not found: {self.state_file}",
                details={"path": str(self.state_file)},
            )
        state_records = flatten_records(load_json(self.state_file))

        async with self.session_factory() as session:
            mailbox_id = await self._import_mailbox_and_folders(session)
            if not self.dry_run:
                await session.commit()

            for record in state_records:
                record_key = str(record.get("record_key") or "").strip()
                if not record_key:
                    self._record_error("<missing>", "Record has no record_key.")
                    continue
                # SAVEPOINT per record: a malformed record rolls back alone.
                nested = await session.begin_nested()
                try:
                    status = await self._import_record(session, mailbox_id, record_key, record)
                except Exception as exc:
                    await nested.rollback()
                    self._record_error(record_key, str(exc))
                    continue
                await nested.commit()
                if not self.dry_run:
                    await session.commit()
                self._record_ok(record_key, status)

            if self.dry_run:
                await session.rollback()
        return self.report

    def _record_ok(self, record_key: str, status: str) -> None:
        self.report.records.append(RecordResult(record_key=record_key, status=status))
        if status == "inserted":
            self.report.inserted += 1
        elif status == "updated":
            self.report.updated += 1
        else:
            self.report.skipped += 1

    def _record_error(self, record_key: str, reason: str) -> None:
        logger.warning("Prototype record %s failed to import: %s", record_key, reason)
        self.report.records.append(
            RecordResult(record_key=record_key, status="error", reason=reason)
        )
        self.report.errors += 1

    # -------------------------------------------------------- mailbox/folders

    async def _import_mailbox_and_folders(self, session: AsyncSession) -> uuid.UUID:
        repo = MailboxRepository(session)
        mailbox = await repo.get_by_address(self.mailbox_address)
        if mailbox is None:
            mailbox = await repo.create(address=self.mailbox_address)

        folders_file = self.root / "mailbox_folders.json"
        if folders_file.exists():
            for entry in flatten_records(load_json(folders_file)):
                graph_folder_id = entry.get("graph_folder_id")
                if not graph_folder_id:
                    continue
                existing = await repo.get_folder_by_graph_id(mailbox.id, graph_folder_id)
                if existing is not None:
                    continue
                session.add(
                    MailboxFolder(
                        mailbox_id=mailbox.id,
                        graph_folder_id=graph_folder_id,
                        parent_graph_folder_id=entry.get("parent_folder_id"),
                        display_name=entry.get("display_name") or "(unknown)",
                        folder_path=entry.get("folder_path"),
                        purpose=entry.get("purpose"),
                        is_hidden=bool(entry.get("is_hidden", False)),
                        last_verified_at=parse_dt(entry.get("last_verified_at")),
                    )
                )
        await session.flush()
        return mailbox.id

    # ----------------------------------------------------------------- record

    async def _import_record(
        self,
        session: AsyncSession,
        mailbox_id: uuid.UUID,
        record_key: str,
        state: dict[str, Any],
    ) -> str:
        message = self._load_message(record_key)
        graph_message_id = state.get("graph_message_id") or (message or {}).get("id")
        if not graph_message_id:
            raise PrototypeImportError(
                "Record has neither a state graph_message_id nor a raw message id."
            )

        existing = await session.scalar(
            select(Email).where(
                Email.mailbox_id == mailbox_id,
                Email.graph_message_id == graph_message_id,
            )
        )
        if existing is not None:
            # Idempotency: a record already imported is left untouched so a
            # repeated import can never duplicate or clobber history.
            return "skipped"

        current_state = ProcessingState(str(state.get("current_state") or "DISCOVERED"))
        resume_state = state.get("failed_stage") or None

        raw_dir = self.record_dir("raw-emails", record_key)
        mime_path = raw_dir / "message.eml"

        body = (message or {}).get("body") or {}
        sender = ((message or {}).get("from") or {}).get("emailAddress") or {}
        sender_email = (state.get("sender_email") or sender.get("address") or "").lower() or None

        email = Email(
            id=uuid.uuid4(),
            mailbox_id=mailbox_id,
            graph_message_id=graph_message_id,
            internet_message_id=state.get("internet_message_id")
            or (message or {}).get("internetMessageId"),
            conversation_id=state.get("conversation_id") or (message or {}).get("conversationId"),
            current_graph_folder_id=state.get("destination_folder_id")
            or (message or {}).get("parentFolderId"),
            subject=state.get("subject") or (message or {}).get("subject"),
            sender_name=sender.get("name"),
            sender_email=sender_email,
            received_at=parse_dt(
                state.get("received_at") or (message or {}).get("receivedDateTime")
            ),
            sent_at=parse_dt((message or {}).get("sentDateTime")),
            body_content_type=body.get("contentType"),
            body_text=body.get("content") if body.get("contentType") == "text" else None,
            body_html=body.get("content") if body.get("contentType") == "html" else None,
            body_preview=(message or {}).get("bodyPreview"),
            has_attachments=bool(
                (message or {}).get("hasAttachments") or state.get("attachment_count")
            ),
            is_read=(message or {}).get("isRead"),
            processing_state=current_state.value,
            resume_state=resume_state,
            retry_count=int(state.get("retry_count") or 0),
            next_retry_at=parse_dt(state.get("next_retry_at")),
            last_error_code=state.get("last_error_code") or None,
            last_error_message=state.get("last_error_message") or None,
            raw_message_storage_uri=to_file_uri(str(mime_path)) if mime_path.exists() else None,
            source_payload={"prototype_record_key": record_key},
            discovered_at=parse_dt(state.get("discovered_at")),
            completed_at=parse_dt(state.get("completed_at")),
        )
        session.add(email)
        await session.flush()

        self._import_recipients(session, email, message)
        self._import_attachments(session, email, record_key)
        self._import_history(session, email, state)
        classification = self._import_classification(session, email, record_key)
        review = self._import_review(session, classification, record_key)
        task = self._import_task(session, email, classification, review, record_key, state)
        self._import_draft(session, email, task, state)

        session.add(
            AuditEvent(
                actor_type=ActorType.IMPORT.value,
                actor_id=self.actor_id,
                entity_type="email",
                entity_id=str(email.id),
                action="prototype_import",
                after_data={"record_key": record_key, "state": current_state.value},
                event_metadata={"source": "powershell-prototype"},
                occurred_at=utcnow(),
            )
        )
        await session.flush()
        return "inserted"

    def _load_message(self, record_key: str) -> dict[str, Any] | None:
        path = self.record_dir("raw-emails", record_key) / "message.json"
        if not path.exists():
            return None
        records = flatten_records(load_json(path))
        return records[0] if records else None

    def _import_recipients(
        self, session: AsyncSession, email: Email, message: dict[str, Any] | None
    ) -> None:
        if not message:
            return
        mapping = {
            "toRecipients": "TO",
            "ccRecipients": "CC",
            "bccRecipients": "BCC",
            "replyTo": "REPLY_TO",
        }
        for graph_key, recipient_type in mapping.items():
            for ordinal, entry in enumerate(message.get(graph_key) or []):
                address = ((entry or {}).get("emailAddress") or {}).get("address")
                if not address:
                    continue
                session.add(
                    EmailRecipient(
                        email_id=email.id,
                        recipient_type=recipient_type,
                        display_name=((entry or {}).get("emailAddress") or {}).get("name"),
                        address=address.strip().lower(),
                        ordinal=ordinal,
                    )
                )

    def _import_attachments(self, session: AsyncSession, email: Email, record_key: str) -> None:
        manifest_path = self.record_dir("attachments", record_key) / "attachment_manifest.json"
        if not manifest_path.exists():
            return
        for entry in flatten_records(load_json(manifest_path)):
            attachment_id = entry.get("attachment_id")
            if not attachment_id:
                continue
            session.add(
                EmailAttachment(
                    email_id=email.id,
                    graph_attachment_id=attachment_id,
                    attachment_type=entry.get("attachment_type"),
                    original_filename=entry.get("original_filename"),
                    stored_filename=entry.get("stored_filename"),
                    mime_type=entry.get("mime_type"),
                    graph_size_bytes=entry.get("graph_size_bytes"),
                    stored_size_bytes=entry.get("local_size_bytes"),
                    is_inline=bool(entry.get("is_inline", False)),
                    storage_uri=to_file_uri(entry.get("storage_path")),
                    sha256_checksum=(entry.get("sha256_checksum") or None),
                    status=str(entry.get("status") or "DISCOVERED"),
                    downloaded_at=parse_dt(entry.get("downloaded_at")),
                )
            )

    def _import_history(self, session: AsyncSession, email: Email, state: dict[str, Any]) -> None:
        for entry in state.get("history") or []:
            to_state = entry.get("to_state")
            if not to_state:
                continue
            session.add(
                EmailProcessingEvent(
                    email_id=email.id,
                    from_state=entry.get("from_state") or None,
                    to_state=to_state,
                    event_type="prototype_history",
                    note=entry.get("note"),
                    error_code=entry.get("error_code") or None,
                    error_message=entry.get("error_message") or None,
                    event_metadata={"source": "powershell-prototype"},
                    occurred_at=parse_dt(entry.get("occurred_at")) or utcnow(),
                )
            )

    def _import_classification(
        self, session: AsyncSession, email: Email, record_key: str
    ) -> Classification | None:
        path = self.record_dir("classifications", record_key) / "classification.json"
        if not path.exists():
            return None
        records = flatten_records(load_json(path))
        if not records:
            return None
        data = records[0]
        llm = data.get("llm") or {}
        classification = Classification(
            id=uuid.uuid4(),
            email_id=email.id,
            version=1,
            schema_version=str(data.get("schema_version") or "1.0"),
            vendor=data.get("vendor"),
            email_type=str(data.get("email_type")),
            states=list(data.get("states") or []),
            license_types=list(data.get("license_types") or []),
            license_numbers=list(data.get("license_numbers") or []),
            requested_information=list(data.get("requested_information") or []),
            documents=list(data.get("documents") or []),
            action_required=bool(data.get("action_required")),
            due_date=parse_date(data.get("due_date")),
            summary=data.get("summary"),
            proposed_action=data.get("proposed_action"),
            confidence=data.get("confidence"),
            requires_human_review=bool(data.get("requires_human_review")),
            classification_method=str(data.get("classification_method") or "unknown"),
            rule_matches=list(data.get("rule_matches") or []),
            model_provider="openai" if llm.get("requested") else None,
            model_name=llm.get("model"),
            model_output=llm or None,
            evidence=self._sanitize_evidence(data.get("evidence") or {}),
            is_current=True,
        )
        session.add(classification)
        return classification

    def _sanitize_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Convert local Windows evidence paths to file:// URIs."""
        clean: dict[str, Any] = {}
        for key, value in evidence.items():
            if isinstance(value, str) and len(value) > 3 and value[1] == ":" and "\\" in value:
                clean[key] = to_file_uri(value)
            else:
                clean[key] = value
        return clean

    def _import_review(
        self,
        session: AsyncSession,
        classification: Classification | None,
        record_key: str,
    ) -> ClassificationReview | None:
        path = self.record_dir("reviews", record_key) / "review.json"
        if not path.exists() or classification is None:
            return None
        records = flatten_records(load_json(path))
        if not records:
            return None
        data = records[0]
        decision = str(data.get("decision"))
        review = ClassificationReview(
            id=uuid.uuid4(),
            classification_id=classification.id,
            decision=decision,
            reviewer_principal=str(data.get("reviewer") or "unknown"),
            review_notes=data.get("review_notes") or None,
            corrected_classification=(
                data.get("reviewed_classification") if decision == "CORRECTED" else None
            ),
            reviewed_at=parse_dt(data.get("reviewed_at")) or utcnow(),
        )
        session.add(review)
        return review

    def _import_task(
        self,
        session: AsyncSession,
        email: Email,
        classification: Classification | None,
        review: ClassificationReview | None,
        record_key: str,
        state: dict[str, Any],
    ) -> LicensingTask | None:
        task_id = state.get("task_id")
        if not task_id:
            return None
        path = self.root / "processing" / "tasks" / f"{task_id}.json"
        if not path.exists():
            return None
        records = flatten_records(load_json(path))
        if not records:
            return None
        data = records[0]
        status = str(data.get("status") or TaskStatus.OPEN.value)
        task = LicensingTask(
            id=uuid.uuid4(),
            task_key=str(data.get("task_id") or task_id),
            email_id=email.id,
            classification_id=classification.id if classification else None,
            review_id=review.id if review else None,
            title=str(data.get("title") or data.get("source_subject") or task_id),
            queue=str(data.get("queue") or "unassigned"),
            status=status,
            destination_folder_name=data.get("destination_folder_name"),
            destination_folder_id=data.get("destination_folder_id"),
            due_date=parse_date(data.get("due_date")),
            vendor=data.get("vendor"),
            email_type=data.get("email_type"),
            proposed_action=data.get("proposed_action"),
            draft_required=bool(data.get("draft_required")),
            draft_status=str(data.get("draft_status") or DraftStatus.NOT_REQUIRED.value),
            completed_at=parse_dt(data.get("completed_at")),
        )
        session.add(task)
        for order, item in enumerate(data.get("requested_information") or []):
            session.add(
                TaskRequestedItem(
                    task_id=task.id,
                    item_text=str(item),
                    status="OPEN",
                    sort_order=order,
                )
            )
        return task

    def _import_draft(
        self,
        session: AsyncSession,
        email: Email,
        task: LicensingTask | None,
        state: dict[str, Any],
    ) -> None:
        if task is None or not state.get("draft_message_id"):
            return
        session.add(
            OutboundDraft(
                task_id=task.id,
                mailbox_id=email.mailbox_id,
                graph_draft_message_id=state.get("draft_message_id"),
                status={
                    "PENDING": "LOCAL_DRAFT",
                    "CREATED": "GRAPH_DRAFT_CREATED",
                    "SENT": "SENT_COPY_VERIFIED",
                    "FAILED": "SEND_FAILED_REVIEW",
                }.get(str(state.get("draft_status") or DraftStatus.CREATED.value), "LOCAL_DRAFT"),
                subject=str(state.get("subject") or "Imported response"),
                graph_web_link=state.get("draft_web_link"),
                created_by=state.get("reviewer"),
                sent_at=parse_dt(state.get("draft_sent_at")),
            )
        )
