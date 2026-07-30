"""Human attestation/payment/final-submit handoffs and governed evidence."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.models import (
    HumanHandoff,
    PortalAttestationRecord,
    PortalPaymentRecord,
    PortalRun,
    SubmissionEvidence,
)
from app.schemas.portal import (
    AttestationOut,
    CaptureSubmissionResult,
    ExternalPayment,
    HandoffOut,
    HumanCompletion,
    PaymentOut,
    RunOut,
    SignatureCompletion,
    SubmissionEvidenceCreate,
    SubmissionEvidenceOut,
)
from app.services.submission_evidence_service import SubmissionEvidenceService

router = APIRouter(tags=["portal-submission"])

ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
SignatoryDep = Annotated[CurrentActor, Depends(require_role(Role.AUTHORIZED_SIGNATORY))]
PaymentApproverDep = Annotated[CurrentActor, Depends(require_role(Role.PAYMENT_APPROVER))]
FinalSubmitterDep = Annotated[CurrentActor, Depends(require_role(Role.FINAL_SUBMITTER))]


@router.get("/portal-runs/{run_id}/attestations", response_model=list[AttestationOut])
async def list_attestations(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[PortalAttestationRecord]:
    return list(
        await session.scalars(
            select(PortalAttestationRecord)
            .where(PortalAttestationRecord.portal_run_id == run_id)
            .order_by(PortalAttestationRecord.created_at)
        )
    )


@router.post(
    "/portal-attestations/{attestation_id}/record-human-completion",
    response_model=AttestationOut,
)
async def record_attestation(
    attestation_id: uuid.UUID,
    payload: HumanCompletion,
    session: SessionDep,
    settings: SettingsDep,
    actor: SignatoryDep,
) -> PortalAttestationRecord:
    return await SubmissionEvidenceService(session, settings).record_attestation_completion(
        attestation_id,
        actor=actor,
        **payload.model_dump(exclude_none=True),
    )


@router.get("/portal-runs/{run_id}/payment", response_model=PaymentOut | None)
async def get_payment(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> PortalPaymentRecord | None:
    payment: PortalPaymentRecord | None = await session.scalar(
        select(PortalPaymentRecord).where(PortalPaymentRecord.portal_run_id == run_id)
    )
    return payment


@router.post(
    "/portal-signature-handoffs/{handoff_id}/record-human-completion",
    response_model=HandoffOut,
)
async def record_signature(
    handoff_id: uuid.UUID,
    payload: SignatureCompletion,
    session: SessionDep,
    settings: SettingsDep,
    actor: SignatoryDep,
) -> HumanHandoff:
    return await SubmissionEvidenceService(session, settings).record_signature_completion(
        handoff_id,
        actor=actor,
        evidence_reference=payload.evidence_reference,
    )


@router.post("/portal-payments/{payment_id}/approve", response_model=PaymentOut)
async def approve_payment(
    payment_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: PaymentApproverDep,
) -> PortalPaymentRecord:
    return await SubmissionEvidenceService(session, settings).approve_payment(
        payment_id, actor=actor
    )


@router.post(
    "/portal-payments/{payment_id}/record-external-payment",
    response_model=PaymentOut,
)
async def record_external_payment(
    payment_id: uuid.UUID,
    payload: ExternalPayment,
    session: SessionDep,
    settings: SettingsDep,
    actor: PaymentApproverDep,
) -> PortalPaymentRecord:
    return await SubmissionEvidenceService(session, settings).record_external_payment(
        payment_id,
        actor=actor,
        **payload.model_dump(exclude_none=True),
    )


@router.post(
    "/portal-runs/{run_id}/request-final-submit-handoff",
    response_model=HandoffOut,
)
async def request_final_submit_handoff(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: FinalSubmitterDep,
) -> HumanHandoff:
    return await SubmissionEvidenceService(session, settings).request_final_submit_handoff(
        run_id, actor=actor
    )


@router.post("/portal-runs/{run_id}/capture-submission-result", response_model=RunOut)
async def capture_submission_result(
    run_id: uuid.UUID,
    payload: CaptureSubmissionResult,
    session: SessionDep,
    settings: SettingsDep,
    actor: FinalSubmitterDep,
) -> PortalRun:
    return await SubmissionEvidenceService(session, settings).request_submission_reconciliation(
        run_id,
        actor=actor,
        reported_outcome=payload.outcome,
        reported_page_category=payload.resulting_page_category,
        reported_ambiguous=payload.ambiguous,
    )


@router.get(
    "/portal-runs/{run_id}/submission-evidence",
    response_model=list[SubmissionEvidenceOut],
)
async def list_submission_evidence(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[SubmissionEvidence]:
    return list(
        await session.scalars(
            select(SubmissionEvidence)
            .where(SubmissionEvidence.portal_run_id == run_id)
            .order_by(SubmissionEvidence.created_at)
        )
    )


@router.post(
    "/portal-runs/{run_id}/submission-evidence",
    response_model=SubmissionEvidenceOut,
    status_code=201,
)
async def add_submission_evidence(
    run_id: uuid.UUID,
    payload: SubmissionEvidenceCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> SubmissionEvidence:
    return await SubmissionEvidenceService(session, settings).add_evidence(
        run_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )
