"""Plan, run, or verify filesystem-to-SharePoint evidence migration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.evidence.migration import EvidenceMigrationService
from app.evidence.sharepoint import SharePointEvidenceStore
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    if args.source != "filesystem" or args.target != "sharepoint":
        raise SystemExit("Only filesystem -> sharepoint migration is supported.")
    settings = get_settings()
    if not settings.sharepoint_site_id:
        raise SystemExit("SHAREPOINT_SITE_ID is required.")
    ctx = WorkerContext.build(settings, worker_id="migrate-evidence")
    client = SharePointClient(ctx.graph_client, settings)
    store = SharePointEvidenceStore(client, site_id=settings.sharepoint_site_id)
    try:
        async with ctx.session_factory() as session:
            service = EvidenceMigrationService(session, store)
            if args.command == "run":
                if not args.confirm:
                    raise SystemExit("run requires --confirm")
                result = await service.run()
            else:
                result = await service.plan()
            print(json.dumps(result.to_dict(), indent=2))
        return 0
    finally:
        await client.aclose()
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate governed evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--source", default="filesystem")
        command.add_argument("--target", default="sharepoint")
        if name == "run":
            command.add_argument("--confirm", action="store_true")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
