"""Operational dashboard and data-quality endpoints."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import ColumnElement, func, select

from app.api.dependencies import ActorDep, SessionDep
from app.models import (
    CaseInformationRequest,
    ComplianceCase,
    ComplianceDeadline,
    ComplianceObligation,
    DocumentPacket,
    FormInstance,
    InformationDefinition,
    InformationValue,
    LicenseInventory,
    RequirementAssessment,
    RequirementSource,
    RequirementSourceSnapshot,
)
from app.models.mixins import utcnow
from app.schemas.licensing import (
    CurrentTrackerOut,
    DashboardSummaryOut,
    DataQualityReportOut,
)
from app.services.current_tracker_service import TrackerWindow, current_tracker
from app.services.licensing_data_quality import LicensingDataQualityService

router = APIRouter(prefix="/licensing-dashboard", tags=["licensing-dashboard"])


async def _count(session: SessionDep, model: type[Any], *where: ColumnElement[bool]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


@router.get("/summary", response_model=DashboardSummaryOut)
async def summary(session: SessionDep, actor: ActorDep) -> DashboardSummaryOut:
    today = utcnow().date()
    expiration_counts: dict[str, int] = {}
    for window in (120, 90, 60, 30):
        expiration_counts[str(window)] = await _count(
            session,
            LicenseInventory,
            LicenseInventory.expiration_date.is_not(None),
            LicenseInventory.expiration_date >= today,
            LicenseInventory.expiration_date <= today + timedelta(days=window),
        )
    stage_rows = (
        await session.execute(
            select(ComplianceCase.current_stage, func.count()).group_by(
                ComplianceCase.current_stage
            )
        )
    ).all()
    return DashboardSummaryOut(
        licenses_total=await _count(session, LicenseInventory),
        licenses_active=await _count(
            session, LicenseInventory, LicenseInventory.current_status == "ACTIVE"
        ),
        licenses_expiring=expiration_counts,
        obligations_overdue=await _count(
            session,
            ComplianceObligation,
            ComplianceObligation.next_due_date < today,
            ComplianceObligation.status.in_(("PLANNED", "ACTIVE", "IN_CASE")),
        ),
        cases_open=await _count(
            session,
            ComplianceCase,
            ComplianceCase.status.not_in(("COMPLETED", "CANCELLED")),
        ),
        cases_blocked=await _count(session, ComplianceCase, ComplianceCase.status == "BLOCKED"),
        cases_overdue=await _count(session, ComplianceCase, ComplianceCase.status == "OVERDUE"),
        cases_by_stage={str(stage): int(count) for stage, count in stage_rows},
        information_requests_open=await _count(
            session,
            CaseInformationRequest,
            CaseInformationRequest.status.in_(
                ("OPEN", "REQUESTED", "ANSWER_PROPOSED", "ANSWER_REVIEW")
            ),
        ),
        information_values_stale=await _count(
            session,
            InformationValue,
            InformationValue.status == "APPROVED",
            InformationValue.valid_to.is_not(None),
            InformationValue.valid_to < today,
        ),
        forms_waiting_signature=await _count(
            session, FormInstance, FormInstance.status == "SIGNATURE_PENDING"
        ),
        forms_waiting_information=await _count(
            session, FormInstance, FormInstance.status == "MISSING_INFORMATION"
        ),
        packets_missing_items=await _count(
            session, DocumentPacket, DocumentPacket.status == "MISSING_ITEMS"
        ),
        sources_stale=await _count(
            session, RequirementSource, RequirementSource.verification_status == "STALE"
        ),
        source_changes_pending=await _count(
            session,
            RequirementSourceSnapshot,
            RequirementSourceSnapshot.review_status == "PENDING_REVIEW",
        ),
        assessments_counsel_review=await _count(
            session,
            RequirementAssessment,
            RequirementAssessment.status == "COUNSEL_REVIEW",
        ),
    )


@router.get("/upcoming-deadlines")
async def upcoming_deadlines(
    session: SessionDep, actor: ActorDep, days: int = 120
) -> list[dict[str, object]]:
    now = utcnow()
    rows = list(
        await session.scalars(
            select(ComplianceDeadline)
            .where(
                ComplianceDeadline.status.not_in(("COMPLETED", "CANCELLED")),
                ComplianceDeadline.due_at <= now + timedelta(days=max(1, min(days, 3650))),
            )
            .order_by(ComplianceDeadline.due_at)
            .limit(500)
        )
    )
    return [
        {
            "id": str(row.id),
            "obligation_id": str(row.obligation_id),
            "deadline_type": row.deadline_type,
            "due_at": row.due_at.isoformat(),
            "status": row.status,
            "severity": row.severity,
            "assigned_owner": row.assigned_owner,
        }
        for row in rows
    ]


@router.get("/current-tracker", response_model=CurrentTrackerOut)
async def current_tracker_snapshot(
    actor: ActorDep, window: TrackerWindow = "ALL"
) -> dict[str, Any]:
    """Return the minimized snapshot built from the maintained tracker sheets."""
    return current_tracker(window=window)


@router.get("/stale-information")
async def stale_information(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    today = utcnow().date()
    rows = (
        await session.execute(
            select(InformationValue, InformationDefinition)
            .join(
                InformationDefinition,
                InformationDefinition.id == InformationValue.information_definition_id,
            )
            .where(
                InformationValue.status == "APPROVED",
                InformationValue.valid_to.is_not(None),
                InformationValue.valid_to < today,
            )
        )
    ).all()
    return [
        {
            "value_id": str(value.id),
            "information_key": definition.information_key,
            "legal_entity_id": (str(value.legal_entity_id) if value.legal_entity_id else None),
            "owner_actor": value.owner_actor,
            "valid_to": value.valid_to.isoformat() if value.valid_to else None,
            "display_value_redacted": value.display_value_redacted,
        }
        for value, definition in rows
    ]


@router.get("/missing-documents")
async def missing_documents(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(DocumentPacket)
            .where(DocumentPacket.status == "MISSING_ITEMS")
            .order_by(DocumentPacket.created_at.desc())
        )
    )
    return [
        {
            "packet_id": str(row.id),
            "case_id": str(row.compliance_case_id),
            "packet_key": row.packet_key,
            "missing_items": row.missing_items,
        }
        for row in rows
    ]


@router.get("/blocked-cases")
async def blocked_cases(session: SessionDep, actor: ActorDep) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(ComplianceCase)
            .where(ComplianceCase.status == "BLOCKED")
            .order_by(ComplianceCase.updated_at.desc())
        )
    )
    return [
        {
            "id": str(row.id),
            "case_key": row.case_key,
            "stage": row.current_stage,
            "assigned_owner": row.assigned_owner,
            "blocked_reason": row.blocked_reason,
        }
        for row in rows
    ]


@router.get("/data-quality", response_model=DataQualityReportOut)
async def data_quality(session: SessionDep, actor: ActorDep) -> dict[str, object]:
    return await LicensingDataQualityService(session).run()
