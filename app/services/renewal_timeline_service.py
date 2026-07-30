"""One chronological account of what has happened to a licence.

A renewal's history is scattered across five tables by design — mail, case
stages, licence status, filings, and outbound replies each have their own
lifecycle. Answering "where are we with this licence?" means reading all five,
which is why this view exists.

It is strictly read-only and derives everything from records already written by
the workflows that own them. Nothing here infers a status: an event appears
because some service recorded it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.licensing.enums import CaseEmailLinkStatus, CaseStatus
from app.models import (
    CaseEmailLink,
    ComplianceCase,
    ComplianceCaseStageEvent,
    Email,
    LegalEntity,
    LicenseInventory,
    LicenseStatusEvent,
    OutboundDraft,
)
from app.schemas.licensing import RenewalTimelineEntry, RenewalTimelineOut

_OPEN_CASE_STATUSES = tuple(
    status.value
    for status in CaseStatus
    if status.value not in {CaseStatus.COMPLETED.value, CaseStatus.CANCELLED.value}
)


class RenewalTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, license_id: uuid.UUID) -> RenewalTimelineOut:
        licence = await self.session.get(LicenseInventory, license_id)
        if licence is None:
            raise NotFoundError("License does not exist.")

        cases = list(
            await self.session.scalars(
                select(ComplianceCase).where(ComplianceCase.license_id == license_id)
            )
        )
        case_by_id = {case.id: case for case in cases}
        entries: list[RenewalTimelineEntry] = []

        entries.extend(await self._license_events(license_id))
        if cases:
            entries.extend(await self._case_stage_events(case_by_id))
            entries.extend(await self._correspondence(case_by_id))
            entries.extend(await self._outbound_replies(case_by_id))

        entries.sort(key=lambda entry: entry.occurred_at)

        open_cases = [case for case in cases if case.status in _OPEN_CASE_STATUSES]
        # The stage a person would quote if asked "where are we?" — the most
        # recently updated open case, not a summary across several.
        active = max(open_cases, key=lambda case: case.updated_at, default=None)
        return RenewalTimelineOut(
            license_id=str(licence.id),
            license_key=licence.license_key,
            current_status=licence.current_status,
            expiration_date=(
                licence.expiration_date.isoformat() if licence.expiration_date else None
            ),
            renewal_due_date=(
                licence.renewal_due_date.isoformat() if licence.renewal_due_date else None
            ),
            open_case_count=len(open_cases),
            active_stage=active.current_stage if active else None,
            entries=entries,
        )

    async def _license_events(self, license_id: uuid.UUID) -> list[RenewalTimelineEntry]:
        rows = await self.session.scalars(
            select(LicenseStatusEvent).where(LicenseStatusEvent.license_id == license_id)
        )
        return [
            RenewalTimelineEntry(
                occurred_at=row.occurred_at.isoformat(),
                category="LICENSE_STATUS",
                summary=(
                    f"Licence status {row.from_status} to {row.to_status}"
                    if row.from_status
                    else f"Licence recorded as {row.to_status}"
                ),
                detail=row.note,
                actor_id=row.actor_id,
                reference={"source_type": row.source_type, "to_status": row.to_status},
            )
            for row in rows
        ]

    async def _case_stage_events(
        self, cases: dict[uuid.UUID, ComplianceCase]
    ) -> list[RenewalTimelineEntry]:
        rows = await self.session.scalars(
            select(ComplianceCaseStageEvent).where(
                ComplianceCaseStageEvent.compliance_case_id.in_(cases)
            )
        )
        entries: list[RenewalTimelineEntry] = []
        for row in rows:
            case = cases[row.compliance_case_id]
            entries.append(
                RenewalTimelineEntry(
                    occurred_at=row.occurred_at.isoformat(),
                    category="CASE_STAGE",
                    summary=(
                        f"Case moved from {row.from_stage} to {row.to_stage}"
                        if row.from_stage
                        else f"Case opened at {row.to_stage}"
                    ),
                    detail=row.reason,
                    actor_id=row.actor_id,
                    case_id=str(case.id),
                    case_key=case.case_key,
                    reference={
                        "to_stage": row.to_stage,
                        "seconds_in_previous_stage": row.seconds_in_previous_stage,
                    },
                )
            )
        return entries

    async def _correspondence(
        self, cases: dict[uuid.UUID, ComplianceCase]
    ) -> list[RenewalTimelineEntry]:
        """Inbound mail a reviewer confirmed as belonging to one of these cases."""
        rows = (
            await self.session.execute(
                select(CaseEmailLink, Email)
                .join(Email, Email.id == CaseEmailLink.email_id)
                .where(
                    CaseEmailLink.compliance_case_id.in_(cases),
                    CaseEmailLink.link_status == CaseEmailLinkStatus.CONFIRMED.value,
                )
            )
        ).all()
        entries: list[RenewalTimelineEntry] = []
        for link, email in rows:
            case = cases[link.compliance_case_id]
            occurred = email.received_at or link.proposed_at
            entries.append(
                RenewalTimelineEntry(
                    occurred_at=occurred.isoformat(),
                    category="EMAIL_RECEIVED",
                    summary=email.subject or "(no subject)",
                    detail=f"From {email.sender_email}" if email.sender_email else None,
                    actor_id=link.decided_by_actor,
                    case_id=str(case.id),
                    case_key=case.case_key,
                    email_id=str(email.id),
                    reference={
                        "conversation_id": link.conversation_id,
                        "confirmed_by": link.decided_by_actor,
                    },
                )
            )
        return entries

    async def _outbound_replies(
        self, cases: dict[uuid.UUID, ComplianceCase]
    ) -> list[RenewalTimelineEntry]:
        """Replies actually sent, tied to the case through its confirmed thread."""
        conversations = {
            case.primary_conversation_id for case in cases.values() if case.primary_conversation_id
        }
        if not conversations:
            return []
        case_by_conversation = {
            case.primary_conversation_id: case
            for case in cases.values()
            if case.primary_conversation_id
        }
        rows = (
            await self.session.execute(
                select(OutboundDraft, Email)
                .join(Email, Email.id == OutboundDraft.email_id)
                .where(
                    Email.conversation_id.in_(conversations),
                    OutboundDraft.sent_at.is_not(None),
                )
            )
        ).all()
        entries: list[RenewalTimelineEntry] = []
        for draft, email in rows:
            case = case_by_conversation.get(email.conversation_id)
            if case is None or draft.sent_at is None:
                continue
            entries.append(
                RenewalTimelineEntry(
                    occurred_at=draft.sent_at.isoformat(),
                    category="EMAIL_SENT",
                    summary=draft.subject or "Reply sent",
                    detail=None,
                    actor_id=draft.approved_by or draft.created_by_actor,
                    case_id=str(case.id),
                    case_key=case.case_key,
                    email_id=str(email.id),
                    reference={"draft_status": draft.draft_status},
                )
            )
        return entries

    async def cases_for_license(self, license_id: uuid.UUID) -> list[dict[str, Any]]:
        """Compact case list for the licence detail page."""
        rows = (
            await self.session.execute(
                select(ComplianceCase, LegalEntity)
                .join(LegalEntity, LegalEntity.id == ComplianceCase.legal_entity_id)
                .where(ComplianceCase.license_id == license_id)
                .order_by(ComplianceCase.created_at.desc())
            )
        ).all()
        return [
            {
                "id": str(case.id),
                "case_key": case.case_key,
                "case_type": case.case_type,
                "current_stage": case.current_stage,
                "status": case.status,
                "priority": case.priority,
                "statutory_due_date": (
                    case.statutory_due_date.isoformat() if case.statutory_due_date else None
                ),
                "assigned_owner": case.assigned_owner,
                "legal_entity_name": entity.legal_name,
                "primary_conversation_linked": bool(case.primary_conversation_id),
            }
            for case, entity in rows
        ]
