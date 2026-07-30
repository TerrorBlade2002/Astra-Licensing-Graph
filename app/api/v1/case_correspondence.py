"""Correspondence links, case threads, and the licence renewal timeline.

Read endpoints answer "where are we with this licence, and on what evidence?".
The two mutating endpoints record a reviewer's decision about a proposed link;
neither sends mail, changes a case stage, nor alters a licence.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.licensing.enums import CaseEmailLinkStatus
from app.models import CaseEmailLink, ComplianceCase, Email, LegalEntity
from app.schemas.licensing import (
    CaseEmailLinkDecision,
    CaseEmailLinkOut,
    CaseThreadMessageOut,
    RenewalTimelineOut,
)
from app.services.case_email_link_service import CaseEmailLinkService
from app.services.renewal_timeline_service import RenewalTimelineService

router = APIRouter(tags=["case-correspondence"])

#: Confirming correspondence is a review judgement, not data entry: it decides
#: which entity's thread becomes part of a regulatory case file.
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]


async def _decorate(session: SessionDep, links: list[CaseEmailLink]) -> list[CaseEmailLinkOut]:
    """Attach the message and entity context a reviewer needs to judge a link."""
    if not links:
        return []
    emails = {
        row.id: row
        for row in await session.scalars(
            select(Email).where(Email.id.in_({link.email_id for link in links}))
        )
    }
    rows = (
        await session.execute(
            select(ComplianceCase, LegalEntity)
            .join(LegalEntity, LegalEntity.id == ComplianceCase.legal_entity_id)
            .where(ComplianceCase.id.in_({link.compliance_case_id for link in links}))
        )
    ).all()
    context = {case.id: (case, entity) for case, entity in rows}

    out: list[CaseEmailLinkOut] = []
    for link in links:
        email = emails.get(link.email_id)
        case, entity = context.get(link.compliance_case_id, (None, None))
        out.append(
            CaseEmailLinkOut(
                id=str(link.id),
                compliance_case_id=str(link.compliance_case_id),
                case_key=case.case_key if case else None,
                email_id=str(link.email_id),
                conversation_id=link.conversation_id,
                link_status=link.link_status,
                match_score=float(link.match_score) if link.match_score is not None else None,
                match_reasons=link.match_reasons,
                proposed_by_actor=link.proposed_by_actor,
                proposed_at=link.proposed_at.isoformat(),
                decided_by_actor=link.decided_by_actor,
                decided_at=link.decided_at.isoformat() if link.decided_at else None,
                decision_reason=link.decision_reason,
                email_subject=email.subject if email else None,
                email_sender=email.sender_email if email else None,
                email_received_at=(
                    email.received_at.isoformat() if email and email.received_at else None
                ),
                legal_entity_name=entity.legal_name if entity else None,
            )
        )
    return out


@router.get("/case-email-links", response_model=list[CaseEmailLinkOut])
async def list_pending_links(
    session: SessionDep,
    actor: ActorDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CaseEmailLinkOut]:
    """The review queue: proposed links awaiting a decision, strongest first."""
    links = await CaseEmailLinkService(session).pending_links(limit=limit)
    return await _decorate(session, links)


@router.get("/compliance-cases/{case_id}/email-links", response_model=list[CaseEmailLinkOut])
async def list_case_links(
    case_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
    status: Annotated[str | None, Query()] = None,
) -> list[CaseEmailLinkOut]:
    if status is not None and status not in {member.value for member in CaseEmailLinkStatus}:
        raise NotFoundError("Unknown link status.")
    links = await CaseEmailLinkService(session).links_for_case(case_id, status=status)
    return await _decorate(session, links)


@router.get("/compliance-cases/{case_id}/thread", response_model=list[CaseThreadMessageOut])
async def case_thread(
    case_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[CaseThreadMessageOut]:
    """Confirmed correspondence for a case, oldest first. Bodies are excluded."""
    case = await session.get(ComplianceCase, case_id)
    if case is None:
        raise NotFoundError("Compliance case does not exist.")
    messages = await CaseEmailLinkService(session).thread_for_case(case_id)
    return [
        CaseThreadMessageOut(
            id=str(message.id),
            conversation_id=message.conversation_id,
            subject=message.subject,
            sender_name=message.sender_name,
            sender_email=message.sender_email,
            received_at=message.received_at.isoformat() if message.received_at else None,
            processing_state=message.processing_state,
            has_attachments=message.has_attachments,
            direction="INBOUND",
        )
        for message in messages
    ]


@router.post("/case-email-links/{link_id}/confirm", response_model=CaseEmailLinkOut)
async def confirm_link(
    link_id: uuid.UUID,
    payload: CaseEmailLinkDecision,
    session: SessionDep,
    actor: ReviewerDep,
) -> CaseEmailLinkOut:
    service = CaseEmailLinkService(session)
    link = await service.confirm(link_id, actor, reason=payload.reason)
    await session.commit()
    decorated = await _decorate(session, [link])
    return decorated[0]


@router.post("/case-email-links/{link_id}/reject", response_model=CaseEmailLinkOut)
async def reject_link(
    link_id: uuid.UUID,
    payload: CaseEmailLinkDecision,
    session: SessionDep,
    actor: ReviewerDep,
) -> CaseEmailLinkOut:
    service = CaseEmailLinkService(session)
    link = await service.reject(link_id, actor, reason=payload.reason)
    await session.commit()
    decorated = await _decorate(session, [link])
    return decorated[0]


@router.get("/licenses/{license_id}/renewal-timeline", response_model=RenewalTimelineOut)
async def renewal_timeline(
    license_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> RenewalTimelineOut:
    """Merged history: licence status, case stages, mail received, replies sent."""
    return await RenewalTimelineService(session).build(license_id)


@router.get("/licenses/{license_id}/cases")
async def license_cases(
    license_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, Any]]:
    return await RenewalTimelineService(session).cases_for_license(license_id)
