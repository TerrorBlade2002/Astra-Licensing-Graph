"""Portal-run workspace, browser-session, field, upload, and snapshot APIs."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_any_role, require_role
from app.auth.roles import Role
from app.core.exceptions import NotFoundError
from app.models import (
    BrowserSession,
    HumanHandoff,
    PortalRun,
    PortalRunDocument,
    PortalRunField,
    PortalRunStep,
    PreSubmissionSnapshot,
)
from app.portals.enums import ACTIVE_BROWSER_SESSION_STATUSES
from app.schemas.portal import (
    BrowserSessionOut,
    DocumentObservation,
    FieldObservation,
    HandoffComplete,
    HandoffOut,
    PortalNavigationRequest,
    RunCreate,
    RunDocumentOut,
    RunFieldOut,
    RunOut,
    RunUpdate,
    SnapshotDecision,
    SnapshotOut,
)
from app.services.portal_entry_service import PortalEntryService
from app.services.portal_run_service import PortalRunService
from app.services.portal_session_service import PortalSessionService

router = APIRouter(tags=["portal-runs"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
OperatorDep = Annotated[CurrentActor, Depends(require_role(Role.PORTAL_OPERATOR))]
HandoffActorDep = Annotated[
    CurrentActor,
    Depends(
        require_any_role(
            Role.PORTAL_OPERATOR,
            Role.AUTHORIZED_SIGNATORY,
            Role.PAYMENT_APPROVER,
            Role.FINAL_SUBMITTER,
        )
    ),
]


@router.get("/portal-runs", response_model=list[RunOut])
async def list_runs(
    session: SessionDep,
    actor: ActorDep,
    status: str | None = None,
    assigned_operator_id: uuid.UUID | None = None,
) -> list[PortalRun]:
    stmt = select(PortalRun).order_by(PortalRun.deadline_at.nulls_last(), PortalRun.created_at)
    if status:
        stmt = stmt.where(PortalRun.status == status)
    if assigned_operator_id:
        stmt = stmt.where(PortalRun.assigned_operator_id == assigned_operator_id)
    return list(await session.scalars(stmt))


@router.post(
    "/compliance-cases/{case_id}/portal-runs",
    response_model=RunOut,
    status_code=201,
)
async def create_run(
    case_id: uuid.UUID,
    payload: RunCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> PortalRun:
    return await PortalRunService(session, settings).create_run(
        case_id,
        actor=actor,
        fields=payload.model_dump(exclude_none=True),
    )


@router.get("/portal-runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> PortalRun:
    run = await session.get(PortalRun, run_id)
    if run is None:
        raise NotFoundError("Portal run not found.")
    return run


@router.patch("/portal-runs/{run_id}", response_model=RunOut)
async def update_run(
    run_id: uuid.UUID,
    payload: RunUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> PortalRun:
    return await PortalRunService(session, settings).update_run(
        run_id, actor=actor, changes=payload.model_dump(exclude_unset=True)
    )


@router.post("/portal-runs/{run_id}/start", response_model=RunOut)
async def start_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalRunService(session, settings).start(run_id, actor=actor)


@router.post("/portal-runs/{run_id}/pause", response_model=RunOut)
async def pause_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalRunService(session, settings).pause(run_id, actor=actor)


@router.post("/portal-runs/{run_id}/navigate", response_model=RunOut, status_code=202)
async def navigate_run(
    run_id: uuid.UUID,
    payload: PortalNavigationRequest,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalRunService(session, settings).queue_navigation(
        run_id,
        actor=actor,
        route_key=payload.route_key,
        request_id=payload.request_id,
    )


@router.post("/portal-runs/{run_id}/resume", response_model=RunOut)
async def resume_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalRunService(session, settings).resume(run_id, actor=actor)


@router.post("/portal-runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> PortalRun:
    return await PortalRunService(session, settings).cancel(run_id, actor=actor)


@router.get("/portal-runs/{run_id}/timeline")
async def run_timeline(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[dict[str, Any]]:
    steps = list(
        await session.scalars(
            select(PortalRunStep)
            .where(PortalRunStep.portal_run_id == run_id)
            .order_by(PortalRunStep.sequence_number)
        )
    )
    return [
        {
            "id": str(step.id),
            "sequence_number": step.sequence_number,
            "step_type": step.step_type,
            "status": step.status,
            "page_category": step.page_category,
            "safe_url_path": step.safe_url_path,
            "result_summary": step.result_summary,
            "started_at": step.started_at,
            "completed_at": step.completed_at,
        }
        for step in steps
    ]


@router.post(
    "/portal-runs/{run_id}/browser-session",
    response_model=BrowserSessionOut,
    status_code=202,
)
async def request_browser_session(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> BrowserSession:
    return await PortalSessionService(session, settings).request_session(run_id, actor=actor)


@router.get("/portal-runs/{run_id}/browser-session", response_model=BrowserSessionOut | None)
async def get_browser_session(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> BrowserSession | None:
    browser_session: BrowserSession | None = await session.scalar(
        select(BrowserSession)
        .where(
            BrowserSession.portal_run_id == run_id,
            BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
        )
        .order_by(BrowserSession.started_at.desc())
    )
    return browser_session


@router.post(
    "/browser-sessions/{browser_session_id}/take-control", response_model=BrowserSessionOut
)
async def take_control(
    browser_session_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> BrowserSession:
    return await PortalSessionService(session, settings).take_control(
        browser_session_id, actor=actor
    )


@router.post(
    "/browser-sessions/{browser_session_id}/return-control",
    response_model=BrowserSessionOut,
)
async def return_control(
    browser_session_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> BrowserSession:
    return await PortalSessionService(session, settings).return_control(
        browser_session_id, actor=actor
    )


@router.post("/browser-sessions/{browser_session_id}/close", response_model=BrowserSessionOut)
async def close_session(
    browser_session_id: uuid.UUID,
    reason: str,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> BrowserSession:
    return await PortalSessionService(session, settings).close(
        browser_session_id, actor=actor, reason=reason
    )


@router.get("/portal-runs/{run_id}/handoffs", response_model=list[HandoffOut])
async def list_handoffs(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[HumanHandoff]:
    return list(
        await session.scalars(
            select(HumanHandoff)
            .where(HumanHandoff.portal_run_id == run_id)
            .order_by(HumanHandoff.requested_at)
        )
    )


@router.get("/handoffs/{handoff_id}", response_model=HandoffOut)
async def get_handoff(handoff_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> HumanHandoff:
    handoff = await session.get(HumanHandoff, handoff_id)
    if handoff is None:
        raise NotFoundError("Human handoff not found.")
    return handoff


@router.post("/handoffs/{handoff_id}/accept", response_model=HandoffOut)
async def accept_handoff(
    handoff_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: HandoffActorDep,
) -> HumanHandoff:
    return await PortalSessionService(session, settings).accept_handoff(handoff_id, actor=actor)


@router.post("/handoffs/{handoff_id}/complete", response_model=HandoffOut, status_code=202)
async def complete_handoff(
    handoff_id: uuid.UUID,
    payload: HandoffComplete,
    session: SessionDep,
    settings: SettingsDep,
    actor: HandoffActorDep,
) -> HumanHandoff:
    return await PortalSessionService(session, settings).request_handoff_completion(
        handoff_id, actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.post("/handoffs/{handoff_id}/decline", response_model=HandoffOut)
async def decline_handoff(
    handoff_id: uuid.UUID,
    reason: str,
    session: SessionDep,
    settings: SettingsDep,
    actor: HandoffActorDep,
) -> HumanHandoff:
    return await PortalSessionService(session, settings).decline_handoff(
        handoff_id, actor=actor, reason=reason
    )


@router.get("/portal-runs/{run_id}/fields", response_model=list[RunFieldOut])
async def list_fields(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[PortalRunField]:
    return list(
        await session.scalars(
            select(PortalRunField)
            .where(PortalRunField.portal_run_id == run_id)
            .order_by(PortalRunField.portal_field_key)
        )
    )


@router.post("/portal-runs/{run_id}/enter-approved-fields", response_model=RunOut, status_code=202)
async def enter_approved_fields(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalEntryService(session, settings).queue_field_entry(run_id, actor=actor)


@router.patch("/portal-run-fields/{field_id}", response_model=RunFieldOut)
async def record_human_field(
    field_id: uuid.UUID,
    payload: FieldObservation,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRunField:
    return await PortalEntryService(session, settings).record_human_field_observation(
        field_id, actor=actor, **payload.model_dump()
    )


@router.post("/portal-run-fields/{field_id}/verify", response_model=RunFieldOut)
async def verify_field(
    field_id: uuid.UUID,
    payload: FieldObservation,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRunField:
    return await PortalEntryService(session, settings).record_human_field_observation(
        field_id, actor=actor, **payload.model_dump()
    )


@router.get("/portal-runs/{run_id}/documents", response_model=list[RunDocumentOut])
async def list_run_documents(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[PortalRunDocument]:
    return list(
        await session.scalars(
            select(PortalRunDocument)
            .where(PortalRunDocument.portal_run_id == run_id)
            .order_by(PortalRunDocument.expected_filename)
        )
    )


@router.post(
    "/portal-runs/{run_id}/upload-approved-documents",
    response_model=RunOut,
    status_code=202,
)
async def upload_documents(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalEntryService(session, settings).queue_document_upload(run_id, actor=actor)


@router.post(
    "/portal-run-documents/{document_id}/verify",
    response_model=RunDocumentOut,
)
async def verify_document(
    document_id: uuid.UUID,
    payload: DocumentObservation,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRunDocument:
    return await PortalEntryService(session, settings).record_document_observation(
        document_id,
        actor_id=actor.actor_id,
        **payload.model_dump(exclude_none=True),
    )


@router.post("/portal-runs/{run_id}/validate", response_model=RunOut, status_code=202)
async def validate_portal_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PortalRun:
    return await PortalRunService(session, settings).queue_validation(run_id, actor=actor)


@router.get("/portal-runs/{run_id}/discrepancies")
async def get_discrepancies(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    snapshot = await session.scalar(
        select(PreSubmissionSnapshot)
        .where(PreSubmissionSnapshot.portal_run_id == run_id)
        .order_by(PreSubmissionSnapshot.version.desc())
    )
    fields = list(
        await session.scalars(
            select(PortalRunField).where(
                PortalRunField.portal_run_id == run_id,
                PortalRunField.status == "DISCREPANCY",
            )
        )
    )
    return {
        "snapshot_id": str(snapshot.id) if snapshot else None,
        "discrepancies": snapshot.discrepancy_report if snapshot else [],
        "field_discrepancies": [
            {
                "field_id": str(field.id),
                "field_key": field.portal_field_key,
                "code": field.discrepancy_code,
                "details": field.discrepancy_details,
            }
            for field in fields
        ],
    }


@router.post(
    "/portal-runs/{run_id}/pre-submission-snapshot",
    response_model=SnapshotOut,
    status_code=201,
)
async def create_snapshot(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: OperatorDep,
) -> PreSubmissionSnapshot:
    return await PortalRunService(session, settings).create_snapshot(run_id, actor=actor)


@router.get("/pre-submission-snapshots/{snapshot_id}", response_model=SnapshotOut)
async def get_snapshot(
    snapshot_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> PreSubmissionSnapshot:
    snapshot = await session.get(PreSubmissionSnapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError("Pre-submission snapshot not found.")
    return snapshot


@router.post("/pre-submission-snapshots/{snapshot_id}/approve", response_model=SnapshotOut)
async def approve_snapshot(
    snapshot_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> PreSubmissionSnapshot:
    return await PortalRunService(session, settings).approve_snapshot(snapshot_id, actor=actor)


@router.post("/pre-submission-snapshots/{snapshot_id}/reject", response_model=SnapshotOut)
async def reject_snapshot(
    snapshot_id: uuid.UUID,
    payload: SnapshotDecision,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> PreSubmissionSnapshot:
    return await PortalRunService(session, settings).reject_snapshot(
        snapshot_id, actor=actor, reason=payload.reason
    )
