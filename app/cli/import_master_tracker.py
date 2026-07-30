"""Plan, apply, or verify a master-tracker import."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.tracker_import_service import TrackerImportService


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with session_scope() as session:
        service = TrackerImportService(session, get_settings())
        if args.command == "verify":
            return await service.report(uuid.UUID(args.run_id))
        content = Path(args.file).read_bytes()
        mapping = json.loads(Path(args.mapping).read_text("utf-8")) if args.mapping else None
        plan = await service.plan(
            actor=operator_actor(args.actor),
            filename=Path(args.file).name,
            content=content,
            mapping=mapping,
            sheet_name=args.sheet,
        )
        if args.command == "plan":
            return plan
        return await service.apply(
            uuid.UUID(str(plan["import_run_id"])),
            actor=operator_actor(args.actor),
            confirm=args.confirm,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--file", required=True)
        command.add_argument("--mapping")
        command.add_argument("--sheet")
        command.add_argument("--actor", default="operator-cli")
        if name == "run":
            command.add_argument("--confirm", action="store_true", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
