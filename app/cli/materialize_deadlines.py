"""Materialize idempotent licensing deadlines and optionally escalate."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.deadline_service import DeadlineService


async def _run(args: argparse.Namespace) -> dict[str, int]:
    async with session_scope() as session:
        service = DeadlineService(session, get_settings())
        if args.obligation_id:
            rows = await service.materialize_for_obligation(
                uuid.UUID(args.obligation_id), actor=operator_actor(args.actor)
            )
            result = {"deadlines_created": len(rows)}
        else:
            result = await service.materialize_all(actor=operator_actor(args.actor))
        if args.escalate:
            result["notifications_created"] = await service.run_escalations(
                manager_actor=args.manager_actor
            )
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obligation-id")
    parser.add_argument("--escalate", action="store_true")
    parser.add_argument("--manager-actor")
    parser.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
