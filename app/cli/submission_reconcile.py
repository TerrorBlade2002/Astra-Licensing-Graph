"""Inspect evidence for an ambiguous submission; never repeats final submit."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import select

from app.cli.licensing_common import session_scope
from app.models import PortalRun, SubmissionEvidence


async def _run(run_id: uuid.UUID) -> dict[str, object]:
    async with session_scope() as session:
        run = await session.get(PortalRun, run_id)
        if run is None:
            return {"run_id": str(run_id), "found": False}
        evidence = list(
            await session.scalars(
                select(SubmissionEvidence).where(SubmissionEvidence.portal_run_id == run.id)
            )
        )
        return {
            "run_id": str(run.id),
            "found": True,
            "status": run.status,
            "evidence_count": len(evidence),
            "verified_evidence_count": sum(item.verified_at is not None for item in evidence),
            "may_retry_final_submit": False,
            "next_action": "human evidence reconciliation",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=uuid.UUID)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args.run_id)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
