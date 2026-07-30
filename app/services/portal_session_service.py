"""Operator-bound browser session and human-handoff coordination."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    FINAL_SUBMIT_HANDOFFS_TOTAL,
    PORTAL_CAPTCHA_HANDOFFS_TOTAL,
    PORTAL_HANDOFFS_TOTAL,
    PORTAL_MFA_HANDOFFS_TOTAL,
)
from app.licensing.audit import add_licensing_audit
from app.models import (
    BrowserSession,
    HumanHandoff,
    PortalRun,
    PortalUserAuthorization,
    UserPrincipal,
)
from app.models.mixins import utcnow
from app.portals.enums import (
    ACTIVE_BROWSER_SESSION_STATUSES,
    BrowserSessionStatus,
    HandoffStatus,
    HandoffType,
    PortalJobType,
    PortalRunStatus,
)
from app.portals.policies import authorization_is_current
from app.repositories.portal_jobs import PortalJobRepository
from app.services.portal_run_service import PortalRunService

_RUN_STATUS_FOR_HANDOFF = {
    HandoffType.LOGIN.value: PortalRunStatus.WAITING_LOGIN.value,
    HandoffType.TERMS_ACCEPTANCE.value: PortalRunStatus.WAITING_TERMS_ACCEPTANCE.value,
    HandoffType.MFA.value: PortalRunStatus.WAITING_MFA.value,
    HandoffType.CAPTCHA.value: PortalRunStatus.WAITING_CAPTCHA.value,
    HandoffType.ATTESTATION.value: PortalRunStatus.WAITING_ATTESTATION.value,
    HandoffType.SIGNATURE.value: PortalRunStatus.WAITING_SIGNATURE.value,
    HandoffType.PAYMENT.value: PortalRunStatus.WAITING_PAYMENT.value,
    HandoffType.FINAL_SUBMIT.value: PortalRunStatus.WAITING_FINAL_SUBMIT.value,
    HandoffType.UNEXPECTED_PAGE.value: PortalRunStatus.FAILED_REVIEW.value,
    HandoffType.PORTAL_ERROR.value: PortalRunStatus.BLOCKED.value,
    HandoffType.SENSITIVE_FIELD.value: PortalRunStatus.BLOCKED.value,
}


class PortalSessionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def request_session(self, run_id: uuid.UUID, *, actor: CurrentActor) -> BrowserSession:
        run = await self._run(run_id)
        await PortalRunService(self.session, self.settings).revalidate_governance(run)
        if not self.settings.portal_automation_enabled or not (
            self.settings.browser_automation_enabled
        ):
            raise StateConflictError("Portal browser assistance is disabled by configuration.")
        if run.status != PortalRunStatus.WAITING_OPERATOR.value:
            raise StateConflictError("Start the governed portal run before requesting a session.")
        if run.assigned_operator_id is None:
            raise StateConflictError("Portal run has no assigned operator.")
        await self._assert_actor_user(actor, run.assigned_operator_id)
        await self._assert_authorization(run)
        existing = await self.session.scalar(
            select(BrowserSession).where(
                BrowserSession.portal_run_id == run.id,
                BrowserSession.operator_user_id == run.assigned_operator_id,
                BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
            )
        )
        if existing:
            return existing
        now = utcnow()
        browser_session = BrowserSession(
            portal_run_id=run.id,
            operator_user_id=run.assigned_operator_id,
            worker_id="pending",
            session_status=BrowserSessionStatus.REQUESTED.value,
            browser_type=self.settings.browser_type,
            ephemeral_profile_id=uuid.uuid4().hex,
            encrypted_session_reference=None,
            started_at=now,
            last_activity_at=now,
            expires_at=now + timedelta(minutes=self.settings.browser_session_max_minutes),
        )
        self.session.add(browser_session)
        await self.session.flush()
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.START_BROWSER_SESSION,
            idempotency_key=f"portal-session-start:{browser_session.id}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=3,
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="browser_session",
            entity_id=browser_session.id,
            action="browser_session_requested",
            after={"portal_run_id": str(run.id), "operator_user_id": str(run.assigned_operator_id)},
        )
        await self.session.commit()
        return browser_session

    async def take_control(self, session_id: uuid.UUID, *, actor: CurrentActor) -> BrowserSession:
        browser_session = await self._session(session_id)
        await self._assert_actor_user(actor, browser_session.operator_user_id)
        if browser_session.session_status != BrowserSessionStatus.ACTIVE_AUTOMATION.value:
            raise StateConflictError("Automation is not currently available for handoff.")
        if browser_session.expires_at <= utcnow():
            browser_session.session_status = BrowserSessionStatus.EXPIRED.value
            raise StateConflictError("Browser session has expired.")
        browser_session.session_status = BrowserSessionStatus.ACTIVE_HUMAN_CONTROL.value
        browser_session.last_activity_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="browser_session",
            entity_id=browser_session.id,
            action="browser_control_taken",
        )
        await self.session.commit()
        return browser_session

    async def return_control(self, session_id: uuid.UUID, *, actor: CurrentActor) -> BrowserSession:
        browser_session = await self._session(session_id)
        await self._assert_actor_user(actor, browser_session.operator_user_id)
        if browser_session.session_status != BrowserSessionStatus.ACTIVE_HUMAN_CONTROL.value:
            raise StateConflictError("Human control is not active.")
        open_handoff = await self.session.scalar(
            select(HumanHandoff.id).where(
                HumanHandoff.browser_session_id == browser_session.id,
                HumanHandoff.status.in_(
                    (
                        HandoffStatus.REQUESTED.value,
                        HandoffStatus.ACCEPTED.value,
                        HandoffStatus.ACTIVE.value,
                    )
                ),
            )
        )
        if open_handoff:
            raise StateConflictError(
                "Complete and verify the active human handoff before returning control."
            )
        browser_session.session_status = BrowserSessionStatus.ACTIVE_AUTOMATION.value
        browser_session.last_activity_at = utcnow()
        await self.session.commit()
        return browser_session

    async def close(
        self, session_id: uuid.UUID, *, actor: CurrentActor, reason: str
    ) -> BrowserSession:
        browser_session = await self._session(session_id)
        await self._assert_actor_user(actor, browser_session.operator_user_id)
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.CLOSE_BROWSER_SESSION,
            idempotency_key=f"portal-close:{browser_session.id}",
            portal_run_id=browser_session.portal_run_id,
            browser_session_id=browser_session.id,
            payload={"reason": reason[:200]},
            max_attempts=3,
        )
        browser_session.session_status = BrowserSessionStatus.PAUSED.value
        run = await self._run(browser_session.portal_run_id)
        if run.status not in {
            PortalRunStatus.SUBMITTED.value,
            PortalRunStatus.COMPLETED.value,
            PortalRunStatus.CANCELLED.value,
        }:
            run.status = PortalRunStatus.WAITING_OPERATOR.value
            run.current_stage = run.status
        await self.session.commit()
        return browser_session

    async def create_handoff(
        self,
        run_id: uuid.UUID,
        *,
        actor: CurrentActor | None,
        handoff_type: str,
        requested_from_user_id: uuid.UUID | None,
        expires_at: object | None = None,
        browser_session_id: uuid.UUID | None = None,
    ) -> HumanHandoff:
        if handoff_type not in {item.value for item in HandoffType}:
            raise StateConflictError("Unknown human handoff type.")
        run = await self._run(run_id)
        await PortalRunService(self.session, self.settings).revalidate_governance(run)
        target_user = requested_from_user_id or self._default_handoff_user(run, handoff_type)
        if target_user is None:
            raise StateConflictError("Handoff has no authorized target user.")
        if await self.session.get(UserPrincipal, target_user) is None:
            raise NotFoundError("Handoff target user not found.")
        if browser_session_id is None:
            active = await self.session.scalar(
                select(BrowserSession).where(
                    BrowserSession.portal_run_id == run.id,
                    BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
                )
            )
            browser_session_id = active.id if active else None
        if browser_session_id is not None:
            candidate = await self.session.get(BrowserSession, browser_session_id)
            if candidate is None or candidate.portal_run_id != run.id:
                raise StateConflictError("Handoff browser session does not belong to this run.")
            if candidate.operator_user_id != target_user:
                # A signatory or payment approver never inherits the operator's
                # authenticated portal state. Their action is completed in
                # their own authorized channel and reconciled with evidence.
                candidate.session_status = BrowserSessionStatus.PAUSED.value
                await PortalJobRepository(self.session).enqueue(
                    job_type=PortalJobType.CLOSE_BROWSER_SESSION,
                    idempotency_key=f"portal-handoff-owner-change:{candidate.id}",
                    portal_run_id=run.id,
                    browser_session_id=candidate.id,
                    payload={"reason": "Human action assigned to a different authorized user."},
                    max_attempts=1,
                )
                browser_session_id = None
        existing = await self.session.scalar(
            select(HumanHandoff).where(
                HumanHandoff.portal_run_id == run.id,
                HumanHandoff.handoff_type == handoff_type,
                HumanHandoff.status.in_(
                    (
                        HandoffStatus.REQUESTED.value,
                        HandoffStatus.ACCEPTED.value,
                        HandoffStatus.ACTIVE.value,
                    )
                ),
            )
        )
        if existing:
            return existing
        handoff = HumanHandoff(
            portal_run_id=run.id,
            browser_session_id=browser_session_id,
            handoff_type=handoff_type,
            status=HandoffStatus.REQUESTED.value,
            requested_from_user_id=target_user,
            requested_at=utcnow(),
            expires_at=expires_at,
        )
        self.session.add(handoff)
        run.status = _RUN_STATUS_FOR_HANDOFF[handoff_type]
        run.current_stage = run.status
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="human_handoff",
            entity_id=handoff.id,
            action="portal_handoff_requested",
            after={"handoff_type": handoff_type, "target_user_id": str(target_user)},
        )
        await self.session.commit()
        PORTAL_HANDOFFS_TOTAL.inc()
        if handoff_type == HandoffType.MFA.value:
            PORTAL_MFA_HANDOFFS_TOTAL.inc()
        elif handoff_type == HandoffType.CAPTCHA.value:
            PORTAL_CAPTCHA_HANDOFFS_TOTAL.inc()
        elif handoff_type == HandoffType.FINAL_SUBMIT.value:
            FINAL_SUBMIT_HANDOFFS_TOTAL.inc()
        return handoff

    async def accept_handoff(self, handoff_id: uuid.UUID, *, actor: CurrentActor) -> HumanHandoff:
        handoff = await self._handoff(handoff_id)
        if handoff.status != HandoffStatus.REQUESTED.value:
            raise StateConflictError("Handoff is not awaiting acceptance.")
        if handoff.expires_at and handoff.expires_at <= utcnow():
            handoff.status = HandoffStatus.EXPIRED.value
            await self.session.commit()
            raise StateConflictError("Handoff has expired.")
        if handoff.requested_from_user_id is None:
            raise StateConflictError("Handoff has no assigned user.")
        await self._assert_actor_user(actor, handoff.requested_from_user_id)
        if handoff.browser_session_id:
            browser_session = await self._session(handoff.browser_session_id)
            if browser_session.operator_user_id != handoff.requested_from_user_id:
                raise StateConflictError(
                    "This handoff cannot reuse another user's authenticated session."
                )
            browser_session.session_status = BrowserSessionStatus.ACTIVE_HUMAN_CONTROL.value
            browser_session.last_activity_at = utcnow()
        handoff.status = HandoffStatus.ACTIVE.value
        handoff.accepted_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="human_handoff",
            entity_id=handoff.id,
            action="portal_handoff_accepted",
            after={"handoff_type": handoff.handoff_type},
        )
        await self.session.commit()
        return handoff

    async def request_handoff_completion(
        self,
        handoff_id: uuid.UUID,
        *,
        actor: CurrentActor,
        result: str,
        operator_confirmation: str | None,
        evidence_reference: str | None,
        observed_page_category: str | None,
    ) -> HumanHandoff:
        handoff = await self._handoff(handoff_id)
        if handoff.status != HandoffStatus.ACTIVE.value:
            raise StateConflictError("Handoff is not under active human control.")
        if handoff.requested_from_user_id is None:
            raise StateConflictError("Handoff has no assigned user.")
        await self._assert_actor_user(actor, handoff.requested_from_user_id)
        if handoff.handoff_type in {
            HandoffType.ATTESTATION.value,
            HandoffType.SIGNATURE.value,
            HandoffType.PAYMENT.value,
            HandoffType.FINAL_SUBMIT.value,
        }:
            raise StateConflictError(
                "Use the dedicated human attestation, external-payment, or "
                "submission-evidence workflow for this handoff."
            )
        if handoff.browser_session_id is None:
            raise StateConflictError("This handoff has no isolated browser session to reconcile.")
        # This is intentionally not marked COMPLETED here. The browser worker
        # must verify the resulting page contract first.
        handoff.result = result[:120]
        handoff.operator_confirmation = (operator_confirmation or "")[:1000] or None
        handoff.evidence_reference = (evidence_reference or "")[:1000] or None
        await PortalJobRepository(self.session).enqueue(
            job_type=PortalJobType.RECONCILE_SESSION,
            idempotency_key=f"portal-handoff-verify:{handoff.id}:{uuid.uuid4().hex}",
            portal_run_id=handoff.portal_run_id,
            browser_session_id=handoff.browser_session_id,
            payload={
                "handoff_id": str(handoff.id),
                "expected_page_category": observed_page_category,
            },
            max_attempts=1,
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="human_handoff",
            entity_id=handoff.id,
            action="portal_handoff_completion_requested",
            after={"handoff_type": handoff.handoff_type, "result": handoff.result},
        )
        await self.session.commit()
        return handoff

    async def decline_handoff(
        self, handoff_id: uuid.UUID, *, actor: CurrentActor, reason: str
    ) -> HumanHandoff:
        handoff = await self._handoff(handoff_id)
        if handoff.status not in {
            HandoffStatus.REQUESTED.value,
            HandoffStatus.ACTIVE.value,
        }:
            raise StateConflictError("Handoff cannot be declined from its current state.")
        if handoff.requested_from_user_id:
            await self._assert_actor_user(actor, handoff.requested_from_user_id)
        handoff.status = HandoffStatus.DECLINED.value
        handoff.result = reason[:120]
        handoff.completed_at = utcnow()
        run = await self._run(handoff.portal_run_id)
        run.status = PortalRunStatus.BLOCKED.value
        run.current_stage = run.status
        run.last_error_code = "human_handoff_declined"
        run.last_error_message = reason[:500]
        await self.session.commit()
        return handoff

    async def _assert_authorization(self, run: PortalRun) -> None:
        authorization = await self.session.scalar(
            select(PortalUserAuthorization).where(
                PortalUserAuthorization.portal_definition_id == run.portal_definition_id,
                PortalUserAuthorization.user_principal_id == run.assigned_operator_id,
            )
        )
        if authorization is None:
            raise StateConflictError("Assigned operator has no portal authorization.")
        decision = authorization_is_current(
            status=authorization.authorization_status,
            expires_at=authorization.expires_at,
            filing_type=run.filing_type,
            legal_entity_id=run.legal_entity_id,
            authorized_filing_types=authorization.authorized_filing_types,
            authorized_entity_ids=authorization.authorized_entity_ids,
        )
        if not decision.allowed:
            raise StateConflictError(decision.reason)

    async def _assert_actor_user(
        self, actor: CurrentActor, expected_user_id: uuid.UUID
    ) -> UserPrincipal:
        principal = await self.session.scalar(
            select(UserPrincipal).where(
                UserPrincipal.tenant_id == actor.tenant_id,
                UserPrincipal.object_id == actor.object_id,
            )
        )
        if principal is None or principal.id != expected_user_id:
            raise StateConflictError("Authenticated user does not own this portal action.")
        return principal

    @staticmethod
    def _default_handoff_user(run: PortalRun, handoff_type: str) -> uuid.UUID | None:
        if handoff_type in {HandoffType.ATTESTATION.value, HandoffType.SIGNATURE.value}:
            return run.assigned_signatory_id
        if handoff_type == HandoffType.PAYMENT.value:
            return run.assigned_payment_approver_id
        return run.assigned_operator_id

    async def _run(self, run_id: uuid.UUID) -> PortalRun:
        run = await self.session.get(PortalRun, run_id)
        if run is None:
            raise NotFoundError("Portal run not found.")
        return run

    async def _session(self, session_id: uuid.UUID) -> BrowserSession:
        browser_session = await self.session.get(BrowserSession, session_id)
        if browser_session is None:
            raise NotFoundError("Browser session not found.")
        return browser_session

    async def _handoff(self, handoff_id: uuid.UUID) -> HumanHandoff:
        handoff = await self.session.get(HumanHandoff, handoff_id)
        if handoff is None:
            raise NotFoundError("Human handoff not found.")
        return handoff
