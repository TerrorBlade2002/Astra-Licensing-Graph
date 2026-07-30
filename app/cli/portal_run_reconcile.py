"""Revalidate a portal run and enqueue non-submitting session reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import select

from app.cli.licensing_common import session_scope
from app.core.config import get_settings
from app.models import BrowserSession, PortalRun
from app.portals.enums import ACTIVE_BROWSER_SESSION_STATUSES, PortalJobType
from app.repositories.portal_jobs import PortalJobRepository
from app.services.portal_run_service import PortalRunService


async def _run(run_id: uuid.UUID) -> dict[str, object]:
    async with session_scope() as session:
        run = await session.get(PortalRun, run_id)
        if run is None:
            return {"run_id": str(run_id), "queued": False, "reason": "not found"}
        await PortalRunService(session, get_settings()).revalidate_governance(run)
        browser_session = await session.scalar(
            select(BrowserSession)
            .where(
                BrowserSession.portal_run_id == run.id,
                BrowserSession.session_status.in_(ACTIVE_BROWSER_SESSION_STATUSES),
            )
            .order_by(BrowserSession.started_at.desc())
        )
        if browser_session is None:
            return {
                "run_id": str(run.id),
                "queued": False,
                "reason": "no active isolated browser session",
            }
        _job, created = await PortalJobRepository(session).enqueue(
            job_type=PortalJobType.RECONCILE_SESSION,
            idempotency_key=f"cli-portal-reconcile:{run.id}:{uuid.uuid4().hex}",
            portal_run_id=run.id,
            browser_session_id=browser_session.id,
            max_attempts=1,
        )
        await session.commit()
        return {
            "run_id": str(run.id),
            "status": run.status,
            "queued": created,
            "operation": "reconcile-only",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=uuid.UUID)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args.run_id)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
