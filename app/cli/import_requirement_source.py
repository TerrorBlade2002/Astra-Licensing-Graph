"""Register a manual requirement-source snapshot without portal scraping."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.requirement_source_service import RequirementSourceService


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with session_scope() as session:
        snapshot, changed = await RequirementSourceService(session, get_settings()).add_snapshot(
            uuid.UUID(args.source_id),
            actor=operator_actor(args.actor),
            content=Path(args.file).read_bytes(),
            content_storage_uri=args.storage_uri,
            change_summary=args.summary,
        )
        return {
            "snapshot_id": str(snapshot.id),
            "version": snapshot.version,
            "changed": changed,
            "review_status": snapshot.review_status,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument(
        "--storage-uri",
        required=True,
        help="Controlled URI where this exact immutable source file is already stored.",
    )
    parser.add_argument("--summary")
    parser.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
