"""Low-cardinality portal workflow gauges."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import (
    PORTAL_RUNS_ACTIVE,
    PORTAL_RUNS_BLOCKED,
    PORTAL_SESSIONS_ACTIVE,
    PORTAL_TERMS_REVIEWS_EXPIRING,
)
from app.models import BrowserSession, PortalReviewVersion, PortalRun
from app.models.mixins import utcnow
from app.portals.enums import (
    ACTIVE_BROWSER_SESSION_STATUSES,
    PortalReviewStatus,
    PortalRunStatus,
)


class PortalMetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def refresh(self) -> None:
        terminal = (
            PortalRunStatus.SUBMITTED.value,
            PortalRunStatus.COMPLETED.value,
            PortalRunStatus.CANCELLED.value,
        )
        active = (
            await self.session.scalar(
                select(func.count()).select_from(PortalRun).where(PortalRun.status.not_in(terminal))
            )
            or 0
        )
        blocked = (
            await self.session.scalar(
                select(func.count())
                .select_from(PortalRun)
                .where(
                    PortalRun.status.in_(
                        (
                            PortalRunStatus.BLOCKED.value,
                            PortalRunStatus.FAILED_REVIEW.value,
                            PortalRunStatus.SUBMISSION_RESULT_PENDING.value,
                        )
                    )
                )
            )
            or 0
        )
        sessions = (
            await self.session.scalar(
                select(func.count())
                .select_from(BrowserSession)
                .where(BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES))
            )
            or 0
        )
        expiring = (
            await self.session.scalar(
                select(func.count())
                .select_from(PortalReviewVersion)
                .where(
                    PortalReviewVersion.status == PortalReviewStatus.APPROVED.value,
                    PortalReviewVersion.valid_to.is_not(None),
                    PortalReviewVersion.valid_to <= utcnow() + timedelta(days=30),
                )
            )
            or 0
        )
        PORTAL_RUNS_ACTIVE.set(active)
        PORTAL_RUNS_BLOCKED.set(blocked)
        PORTAL_SESSIONS_ACTIVE.set(sessions)
        PORTAL_TERMS_REVIEWS_EXPIRING.set(expiring)
