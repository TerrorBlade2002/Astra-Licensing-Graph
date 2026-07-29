"""Operational summary for the authenticated portal."""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.dependencies import ActorDep, SessionDep
from app.models import ClassificationReview, ClassificationRun, LicensingTask

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(session: SessionDep, actor: ActorDep) -> dict[str, object]:
    today = date.today()

    async def count(stmt: Any) -> int:
        return int(await session.scalar(stmt) or 0)

    return {
        "pending_reviews": await count(
            select(func.count())
            .select_from(ClassificationReview)
            .where(ClassificationReview.decision == "PENDING")
        ),
        "claimed_reviews": await count(
            select(func.count())
            .select_from(ClassificationReview)
            .where(ClassificationReview.decision == "IN_REVIEW")
        ),
        "tasks_due_today": await count(
            select(func.count()).select_from(LicensingTask).where(LicensingTask.due_date == today)
        ),
        "tasks_overdue": await count(
            select(func.count())
            .select_from(LicensingTask)
            .where(
                LicensingTask.due_date < today,
                LicensingTask.status.notin_(["COMPLETED", "CANCELLED"]),
            )
        ),
        "tasks_due_7_days": await count(
            select(func.count())
            .select_from(LicensingTask)
            .where(LicensingTask.due_date.between(today, today + timedelta(days=7)))
        ),
        "tasks_due_30_days": await count(
            select(func.count())
            .select_from(LicensingTask)
            .where(LicensingTask.due_date.between(today, today + timedelta(days=30)))
        ),
        "failed_classification_jobs": await count(
            select(func.count())
            .select_from(ClassificationRun)
            .where(ClassificationRun.status.in_(["FAILED_RETRYABLE", "FAILED_REVIEW"]))
        ),
    }
