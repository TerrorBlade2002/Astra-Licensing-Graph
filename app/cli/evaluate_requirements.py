"""Create or evaluate an advisory requirement assessment."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.requirement_assessment_service import RequirementAssessmentService


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with session_scope() as session:
        service = RequirementAssessmentService(session, get_settings())
        if args.assessment_id:
            rows = await service.evaluate(
                uuid.UUID(args.assessment_id), actor=operator_actor(args.actor)
            )
            return {"assessment_id": args.assessment_id, "results": len(rows)}
        facts = json.loads(Path(args.facts).read_text("utf-8")) if args.facts else {}
        assessment = await service.create_assessment(
            actor=operator_actor(args.actor),
            legal_entity_id=uuid.UUID(args.legal_entity_id),
            operating_profile_id=uuid.UUID(args.operating_profile_id),
            requested_jurisdictions=[uuid.UUID(value) for value in args.jurisdiction],
            extra_facts=facts,
        )
        return {"assessment_id": str(assessment.id), "status": assessment.status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment-id")
    parser.add_argument("--legal-entity-id")
    parser.add_argument("--operating-profile-id")
    parser.add_argument("--jurisdiction", action="append", default=[])
    parser.add_argument("--facts")
    parser.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    if not args.assessment_id and not (
        args.legal_entity_id and args.operating_profile_id and args.jurisdiction
    ):
        parser.error("provide --assessment-id or entity/profile/jurisdiction inputs")
    print(json.dumps(asyncio.run(_run(args)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
