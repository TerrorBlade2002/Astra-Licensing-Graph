"""Attach mailbox correspondence to the compliance case it belongs to.

The matcher proposes; a person decides. That split is deliberate: linking one
legal entity's correspondence to another entity's case is the kind of error the
pilot rules say must stop work, so nothing here attaches a thread on its own
authority. Confirmation is what turns a proposal into case evidence.

Matching uses only signals a reviewer could check by eye — a license number
quoted in the message, the jurisdiction, the vendor it came from, and how close
the case's deadline is — and every signal that fired is stored alongside the
link so the review queue can show *why* rather than just a number.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.exceptions import NotFoundError, StateConflictError
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import CaseEmailLinkStatus, CaseStage, CaseStatus
from app.models import (
    CaseEmailLink,
    Classification,
    ComplianceCase,
    Email,
    Jurisdiction,
    LicenseInventory,
    Organization,
)
from app.models.mixins import utcnow

#: Cases in these states are finished; new correspondence should not be
#: proposed against them.
_CLOSED_CASE_STATUSES = frozenset({CaseStatus.COMPLETED.value, CaseStatus.CANCELLED.value})

#: A proposal below this score is noise for a reviewer rather than a lead.
MIN_PROPOSAL_SCORE = 0.30

#: Never flood the queue: only the strongest few candidates per email.
MAX_PROPOSALS_PER_EMAIL = 3

#: A case whose statutory deadline is this far away is still plausibly the
#: subject of an incoming renewal email.
_DEADLINE_WINDOW_DAYS = 180


@dataclass(frozen=True)
class MatchSignal:
    """One reason a case was proposed, with the weight it contributed."""

    code: str
    detail: str
    weight: float


@dataclass
class CaseCandidate:
    case: ComplianceCase
    signals: list[MatchSignal] = field(default_factory=list)

    @property
    def score(self) -> float:
        # Capped at 1.0: several weak signals should never outrank a direct
        # license-number quote, and a score above 1 would read as certainty.
        return min(1.0, round(sum(signal.weight for signal in self.signals), 3))

    def as_reasons(self) -> dict[str, Any]:
        return {
            "signals": [
                {"code": s.code, "detail": s.detail, "weight": s.weight} for s in self.signals
            ]
        }


def _license_number_tokens(value: str | None) -> set[str]:
    """Comparable forms of a license number.

    Regulators and vendors quote the same number inconsistently
    ("MB-12345", "mb 12345", "12345"), so compare on the alphanumeric core.
    """
    if not value:
        return set()
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if len(cleaned) < 4:
        return set()
    digits = re.sub(r"[^0-9]", "", cleaned)
    tokens = {cleaned}
    if len(digits) >= 4:
        tokens.add(digits)
    return tokens


class CaseEmailLinkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------- proposing

    async def propose_for_email(
        self,
        email: Email,
        *,
        actor: CurrentActor | None = None,
        classification: Classification | None = None,
    ) -> list[CaseEmailLink]:
        """Propose candidate cases for one reviewed email.

        Returns the links created. Existing decisions are never overwritten:
        a reviewer's rejection stays rejected on re-processing.
        """
        classification = classification or await self._classification_for(email)
        if classification is None:
            return []

        candidates = await self._rank_candidates(email, classification)
        created: list[CaseEmailLink] = []
        now = utcnow()
        for candidate in candidates[:MAX_PROPOSALS_PER_EMAIL]:
            existing = await self.session.scalar(
                select(CaseEmailLink).where(
                    CaseEmailLink.compliance_case_id == candidate.case.id,
                    CaseEmailLink.email_id == email.id,
                )
            )
            if existing is not None:
                continue
            link = CaseEmailLink(
                compliance_case_id=candidate.case.id,
                email_id=email.id,
                conversation_id=email.conversation_id,
                link_status=CaseEmailLinkStatus.PROPOSED.value,
                match_score=candidate.score,
                match_reasons=candidate.as_reasons(),
                proposed_by_actor=actor.actor_id if actor else "case-link-matcher",
                proposed_at=now,
            )
            self.session.add(link)
            created.append(link)
        if created:
            await self.session.flush()
            add_licensing_audit(
                self.session,
                actor=actor,
                entity_type="email",
                entity_id=email.id,
                action="case_links_proposed",
                after={"proposed_case_ids": [str(link.compliance_case_id) for link in created]},
                metadata={"count": len(created)},
                system_actor_id="case-link-matcher",
            )
        return created

    async def _classification_for(self, email: Email) -> Classification | None:
        row: Classification | None = await self.session.scalar(
            select(Classification)
            .where(Classification.email_id == email.id)
            .order_by(Classification.created_at.desc())
            .limit(1)
        )
        return row

    async def _rank_candidates(
        self, email: Email, classification: Classification
    ) -> list[CaseCandidate]:
        cases = list(
            await self.session.scalars(
                select(ComplianceCase).where(
                    ComplianceCase.status.not_in(tuple(_CLOSED_CASE_STATUSES)),
                    ComplianceCase.current_stage != CaseStage.CANCELLED.value,
                )
            )
        )
        if not cases:
            return []

        licenses = {
            row.id: row
            for row in await self.session.scalars(
                select(LicenseInventory).where(
                    LicenseInventory.id.in_([c.license_id for c in cases if c.license_id])
                )
            )
        }
        quoted = {
            token
            for number in (classification.license_numbers or [])
            for token in _license_number_tokens(number)
        }
        states = {str(value).strip().upper() for value in (classification.states or []) if value}
        vendor_ids = await self._vendor_ids(classification.vendor)
        jurisdiction_ids = await self._jurisdiction_ids(states)
        received_on = (email.received_at or utcnow()).date()

        candidates: list[CaseCandidate] = []
        for case in cases:
            candidate = CaseCandidate(case=case)
            licence = licenses.get(case.license_id) if case.license_id else None

            if licence is not None and quoted:
                licence_tokens = _license_number_tokens(licence.license_number) | (
                    _license_number_tokens(licence.nmls_license_id)
                )
                overlap = quoted & licence_tokens
                if overlap:
                    candidate.signals.append(
                        MatchSignal(
                            "LICENSE_NUMBER",
                            f"Message quotes license number {sorted(overlap)[0]}.",
                            0.60,
                        )
                    )

            if (
                licence is not None
                and jurisdiction_ids
                and licence.jurisdiction_id in (jurisdiction_ids)
            ):
                candidate.signals.append(
                    MatchSignal("JURISDICTION", "Jurisdiction matches the licence.", 0.20)
                )

            if vendor_ids and case.vendor_organization_id in vendor_ids:
                candidate.signals.append(
                    MatchSignal("VENDOR", "Sender organisation matches the case vendor.", 0.20)
                )

            deadline_signal = self._deadline_signal(case, received_on)
            if deadline_signal is not None:
                candidate.signals.append(deadline_signal)

            if case.primary_conversation_id and case.primary_conversation_id == (
                email.conversation_id
            ):
                candidate.signals.append(
                    MatchSignal(
                        "SAME_THREAD",
                        "Message belongs to the thread already linked to this case.",
                        0.80,
                    )
                )

            if candidate.score >= MIN_PROPOSAL_SCORE:
                candidates.append(candidate)

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates

    @staticmethod
    def _deadline_signal(case: ComplianceCase, received_on: date) -> MatchSignal | None:
        due = case.statutory_due_date or case.internal_target_date
        if due is None:
            return None
        delta = abs((due - received_on).days)
        if delta > _DEADLINE_WINDOW_DAYS:
            return None
        # Nearer deadlines are more likely to be the subject of live
        # correspondence, but this alone never reaches the proposal threshold.
        weight = 0.20 if delta <= 60 else 0.10
        return MatchSignal("DEADLINE_PROXIMITY", f"Case is due within {delta} days.", weight)

    async def _vendor_ids(self, vendor_name: str | None) -> set[uuid.UUID]:
        if not vendor_name:
            return set()
        rows = await self.session.scalars(
            select(Organization.id).where(Organization.canonical_name.ilike(vendor_name.strip()))
        )
        return set(rows)

    async def _jurisdiction_ids(self, states: set[str]) -> set[uuid.UUID]:
        if not states:
            return set()
        rows = await self.session.scalars(
            select(Jurisdiction.id).where(Jurisdiction.jurisdiction_key.in_(states))
        )
        return set(rows)

    # -------------------------------------------------------------- deciding

    async def confirm(
        self, link_id: uuid.UUID, actor: CurrentActor, *, reason: str | None = None
    ) -> CaseEmailLink:
        link = await self._pending_link(link_id)
        case = await self.session.get(ComplianceCase, link.compliance_case_id)
        if case is None:
            raise NotFoundError("Compliance case does not exist.")
        now = utcnow()
        link.link_status = CaseEmailLinkStatus.CONFIRMED.value
        link.decided_by_actor = actor.actor_id
        link.decided_at = now
        link.decision_reason = reason
        # The first confirmed thread becomes the case's primary conversation;
        # later threads attach without displacing it.
        if not case.primary_conversation_id and link.conversation_id:
            case.primary_conversation_id = link.conversation_id
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="case_email_link",
            entity_id=link.id,
            action="case_email_link_confirmed",
            before={"link_status": CaseEmailLinkStatus.PROPOSED.value},
            after={"link_status": link.link_status},
            metadata={
                "compliance_case_id": str(link.compliance_case_id),
                "email_id": str(link.email_id),
                "match_score": float(link.match_score) if link.match_score is not None else None,
            },
        )
        await self.session.flush()
        return link

    async def reject(
        self, link_id: uuid.UUID, actor: CurrentActor, *, reason: str | None = None
    ) -> CaseEmailLink:
        link = await self._pending_link(link_id)
        link.link_status = CaseEmailLinkStatus.REJECTED.value
        link.decided_by_actor = actor.actor_id
        link.decided_at = utcnow()
        link.decision_reason = reason
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="case_email_link",
            entity_id=link.id,
            action="case_email_link_rejected",
            before={"link_status": CaseEmailLinkStatus.PROPOSED.value},
            after={"link_status": link.link_status},
            metadata={"reason": reason},
        )
        await self.session.flush()
        return link

    async def _pending_link(self, link_id: uuid.UUID) -> CaseEmailLink:
        link = await self.session.get(CaseEmailLink, link_id)
        if link is None:
            raise NotFoundError("Correspondence link does not exist.")
        if link.link_status != CaseEmailLinkStatus.PROPOSED.value:
            raise StateConflictError(
                f"Link is already {link.link_status.lower()}; it cannot be decided again."
            )
        return link

    # --------------------------------------------------------------- reading

    def _links_for_case(self, case_id: uuid.UUID, *, status: str | None) -> Select[Any]:
        stmt = select(CaseEmailLink).where(CaseEmailLink.compliance_case_id == case_id)
        if status:
            stmt = stmt.where(CaseEmailLink.link_status == status)
        return stmt.order_by(CaseEmailLink.proposed_at.desc())

    async def links_for_case(
        self, case_id: uuid.UUID, *, status: str | None = None
    ) -> list[CaseEmailLink]:
        return list(await self.session.scalars(self._links_for_case(case_id, status=status)))

    async def pending_links(self, *, limit: int = 100) -> list[CaseEmailLink]:
        return list(
            await self.session.scalars(
                select(CaseEmailLink)
                .where(CaseEmailLink.link_status == CaseEmailLinkStatus.PROPOSED.value)
                .order_by(CaseEmailLink.match_score.desc(), CaseEmailLink.proposed_at)
                .limit(max(1, min(limit, 500)))
            )
        )

    async def thread_for_case(self, case_id: uuid.UUID) -> list[Email]:
        """Messages a person has confirmed as belonging to this case.

        Includes the rest of each confirmed thread, so a reviewer sees the whole
        exchange rather than only the message that triggered the match.
        """
        confirmed = await self.links_for_case(case_id, status=CaseEmailLinkStatus.CONFIRMED.value)
        if not confirmed:
            return []
        email_ids = {link.email_id for link in confirmed}
        conversations = {link.conversation_id for link in confirmed if link.conversation_id}
        clause: ColumnElement[bool] = Email.id.in_(email_ids)
        if conversations:
            clause = or_(clause, Email.conversation_id.in_(conversations))
        return list(
            await self.session.scalars(
                select(Email).where(clause).order_by(Email.received_at, Email.created_at)
            )
        )


def deadline_window_days() -> int:
    """Exposed for tests and documentation of the matching window."""
    return _DEADLINE_WINDOW_DAYS
