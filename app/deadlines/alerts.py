"""Notification payload construction for deadline and licensing alerts.

Payloads carry internal UUIDs and workflow metadata only. No licence number, no
regulator name, no officer detail, no restricted registry value — a notification
record is read by many people and must stay safe by construction.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any


class NotificationType:
    """Internal notification categories (section 22)."""

    PORTAL = "PORTAL"
    ASSIGNMENT = "ASSIGNMENT"
    DEADLINE_WARNING = "DEADLINE_WARNING"
    OVERDUE_ESCALATION = "OVERDUE_ESCALATION"
    UNANSWERED_INFORMATION = "UNANSWERED_INFORMATION"
    STALE_SOURCE = "STALE_SOURCE"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    SIGNATURE_PENDING = "SIGNATURE_PENDING"
    SOURCE_CHANGE_REVIEW = "SOURCE_CHANGE_REVIEW"
    STALE_INFORMATION = "STALE_INFORMATION"


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    """A notification ready to persist, with a deterministic idempotency key."""

    notification_type: str
    severity: str
    recipient_actor: str
    title: str
    body: str | None
    entity_type: str
    entity_id: str
    idempotency_key: str
    payload: dict[str, Any]
    escalation_level: str | None = None


def build_idempotency_key(*parts: str | None) -> str:
    """Hash the identifying parts so repeat sweeps collide instead of duplicating."""
    raw = "|".join(part or "-" for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def deadline_alert(
    *,
    deadline_id: uuid.UUID,
    obligation_id: uuid.UUID,
    deadline_type: str,
    recipient_actor: str,
    severity: str,
    level: str | None,
    days_remaining: int,
    is_overdue: bool,
    window_suffix: str,
    compliance_case_id: uuid.UUID | None = None,
) -> NotificationDraft:
    """Build a deadline warning or overdue escalation."""
    if is_overdue:
        title = f"Overdue: {deadline_type.replace('_', ' ').title()} ({abs(days_remaining)}d past)"
        notification_type = NotificationType.OVERDUE_ESCALATION
    else:
        title = f"Due in {days_remaining}d: {deadline_type.replace('_', ' ').title()}"
        notification_type = NotificationType.DEADLINE_WARNING
    return NotificationDraft(
        notification_type=notification_type,
        severity=severity,
        recipient_actor=recipient_actor,
        escalation_level=level,
        title=title,
        body=(
            "Open the compliance calendar to review this obligation. "
            "Dates and ownership are shown in the case workspace."
        ),
        entity_type="compliance_deadline",
        entity_id=str(deadline_id),
        idempotency_key=build_idempotency_key("deadline", str(deadline_id), window_suffix, level),
        payload={
            "deadline_id": str(deadline_id),
            "obligation_id": str(obligation_id),
            "compliance_case_id": str(compliance_case_id) if compliance_case_id else None,
            "deadline_type": deadline_type,
            "days_remaining": days_remaining,
            "is_overdue": is_overdue,
            "escalation_level": level,
        },
    )


def information_request_alert(
    *,
    request_id: uuid.UUID,
    compliance_case_id: uuid.UUID,
    recipient_actor: str,
    severity: str,
    overdue: bool,
    information_key: str | None = None,
) -> NotificationDraft:
    """Assignment or chase notification for an internal information request."""
    return NotificationDraft(
        notification_type=(
            NotificationType.UNANSWERED_INFORMATION if overdue else NotificationType.ASSIGNMENT
        ),
        severity=severity,
        recipient_actor=recipient_actor,
        title=("Information request overdue" if overdue else "Information request assigned to you"),
        body="Answer the request in the portal. Approved answers are reused automatically.",
        entity_type="case_information_request",
        entity_id=str(request_id),
        idempotency_key=build_idempotency_key(
            "info-request", str(request_id), "overdue" if overdue else "assigned"
        ),
        payload={
            "case_information_request_id": str(request_id),
            "compliance_case_id": str(compliance_case_id),
            # A definition key is a schema identifier, not a value; safe to carry.
            "information_key": information_key,
            "overdue": overdue,
        },
    )


def stale_source_alert(
    *,
    source_id: uuid.UUID,
    recipient_actor: str,
    source_type: str,
    freshness_status: str,
) -> NotificationDraft:
    return NotificationDraft(
        notification_type=NotificationType.STALE_SOURCE,
        severity="IMPORTANT",
        recipient_actor=recipient_actor,
        title=f"Requirement source needs verification ({freshness_status})",
        body="Verify the source and record a new snapshot before relying on it again.",
        entity_type="requirement_source",
        entity_id=str(source_id),
        idempotency_key=build_idempotency_key("stale-source", str(source_id), freshness_status),
        payload={
            "requirement_source_id": str(source_id),
            "source_type": source_type,
            "freshness_status": freshness_status,
        },
    )


def source_change_alert(
    *, snapshot_id: uuid.UUID, source_id: uuid.UUID, recipient_actor: str, source_type: str
) -> NotificationDraft:
    return NotificationDraft(
        notification_type=NotificationType.SOURCE_CHANGE_REVIEW,
        severity="IMPORTANT",
        recipient_actor=recipient_actor,
        title="Requirement source changed and needs review",
        body=(
            "A new snapshot is pending review. Active rules are unchanged until a "
            "reviewer decides whether they are affected."
        ),
        entity_type="requirement_source_snapshot",
        entity_id=str(snapshot_id),
        idempotency_key=build_idempotency_key("source-change", str(snapshot_id)),
        payload={
            "requirement_source_snapshot_id": str(snapshot_id),
            "requirement_source_id": str(source_id),
            "source_type": source_type,
        },
    )


def missing_document_alert(
    *,
    packet_id: uuid.UUID,
    compliance_case_id: uuid.UUID,
    recipient_actor: str,
    missing_count: int,
) -> NotificationDraft:
    return NotificationDraft(
        notification_type=NotificationType.MISSING_DOCUMENT,
        severity="IMPORTANT",
        recipient_actor=recipient_actor,
        title=f"Packet is missing {missing_count} document(s)",
        body="Open the packet builder to supply or override the outstanding items.",
        entity_type="document_packet",
        entity_id=str(packet_id),
        idempotency_key=build_idempotency_key("packet-missing", str(packet_id), str(missing_count)),
        payload={
            "document_packet_id": str(packet_id),
            "compliance_case_id": str(compliance_case_id),
            "missing_count": missing_count,
        },
    )


def signature_pending_alert(
    *,
    form_instance_id: uuid.UUID,
    compliance_case_id: uuid.UUID,
    recipient_actor: str,
) -> NotificationDraft:
    return NotificationDraft(
        notification_type=NotificationType.SIGNATURE_PENDING,
        severity="IMPORTANT",
        recipient_actor=recipient_actor,
        title="Form is awaiting an authorised signature",
        body=(
            "The draft is approved for signature. Signing happens outside this "
            "system; record the signed copy when it is returned."
        ),
        entity_type="form_instance",
        entity_id=str(form_instance_id),
        idempotency_key=build_idempotency_key("signature-pending", str(form_instance_id)),
        payload={
            "form_instance_id": str(form_instance_id),
            "compliance_case_id": str(compliance_case_id),
        },
    )


def stale_information_alert(
    *, information_value_id: uuid.UUID, recipient_actor: str, information_key: str, status: str
) -> NotificationDraft:
    return NotificationDraft(
        notification_type=NotificationType.STALE_INFORMATION,
        severity="NORMAL",
        recipient_actor=recipient_actor,
        title=f"Reusable answer needs refreshing ({status})",
        body="Confirm or update the value so it can continue to prefill forms.",
        entity_type="information_value",
        entity_id=str(information_value_id),
        idempotency_key=build_idempotency_key(
            "stale-information", str(information_value_id), status
        ),
        payload={
            "information_value_id": str(information_value_id),
            "information_key": information_key,
            "freshness_status": status,
        },
    )


__all__ = [
    "NotificationDraft",
    "NotificationType",
    "build_idempotency_key",
    "deadline_alert",
    "information_request_alert",
    "missing_document_alert",
    "signature_pending_alert",
    "source_change_alert",
    "stale_information_alert",
    "stale_source_alert",
]
