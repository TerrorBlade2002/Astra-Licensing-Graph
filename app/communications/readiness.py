"""Machine-readable response readiness policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.communications.enums import ReadinessStatus, ResponseType


@dataclass(frozen=True)
class ReadinessResult:
    status: ReadinessStatus
    blockers: tuple[str, ...]


class ResponseReadinessService:
    def evaluate(
        self,
        *,
        response_type: str,
        requested_item_statuses: list[str],
        recipient_count: int,
        draft_reviewed: bool = False,
        send_approved: bool = False,
        graph_draft_exists: bool = False,
        document_blockers: list[str] | None = None,
        unresolved_placeholders: bool = False,
        task_status: str | None = None,
        task_owner: str | None = None,
        destination_folder_id: str | None = None,
        response_deadline: date | None = None,
        check_task_context: bool = False,
    ) -> ReadinessResult:
        blockers = list(document_blockers or [])
        if check_task_context:
            if task_status in {"CANCELLED", "COMPLETED"}:
                blockers.append("TASK_NOT_ACTIONABLE")
            if not destination_folder_id:
                blockers.append("DESTINATION_FOLDER_MISSING")
            if response_type != ResponseType.NO_RESPONSE_REQUIRED and not task_owner:
                blockers.append("TASK_OWNER_MISSING")
            if (
                response_type != ResponseType.NO_RESPONSE_REQUIRED
                and response_deadline
                and response_deadline < date.today()
            ):
                blockers.append("RESPONSE_DEADLINE_PASSED")
        if response_type == ResponseType.NO_RESPONSE_REQUIRED:
            return ReadinessResult(
                ReadinessStatus.BLOCKED if blockers else ReadinessStatus.NOT_REQUIRED,
                tuple(dict.fromkeys(blockers)),
            )
        if recipient_count == 0:
            blockers.append("RECIPIENT_MISSING")
        if unresolved_placeholders:
            blockers.append("UNRESOLVED_PLACEHOLDER")
        if response_type in {
            ResponseType.INFORMATION_RESPONSE,
            ResponseType.DOCUMENT_RESPONSE,
            ResponseType.REGULATOR_RESPONSE,
            ResponseType.BOND_RESPONSE,
        } and any(value not in {"VERIFIED", "NOT_APPLICABLE"} for value in requested_item_statuses):
            blockers.append("REQUESTED_ITEM_NOT_VERIFIED")
        if blockers:
            return ReadinessResult(ReadinessStatus.NOT_READY, tuple(dict.fromkeys(blockers)))
        if not graph_draft_exists:
            return ReadinessResult(ReadinessStatus.READY_FOR_DRAFT, ())
        if not draft_reviewed:
            return ReadinessResult(ReadinessStatus.READY_FOR_APPROVAL, ("DRAFT_NOT_REVIEWED",))
        if not send_approved:
            return ReadinessResult(ReadinessStatus.READY_FOR_APPROVAL, ("SEND_APPROVAL_MISSING",))
        return ReadinessResult(ReadinessStatus.READY_TO_SEND, ())
