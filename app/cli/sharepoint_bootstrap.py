"""Plan, apply, and verify the non-destructive repository bootstrap."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.services.sharepoint_bootstrap import SharePointBootstrapService
from app.services.sharepoint_readiness import SharePointReadinessService
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    ctx = WorkerContext.build(settings, worker_id="sharepoint-bootstrap")
    client = SharePointClient(ctx.graph_client, settings)
    try:
        async with ctx.session_factory() as session:
            service = SharePointBootstrapService(session, client, settings)
            if args.command == "plan":
                result = await service.plan()
            elif args.command == "apply":
                if not args.confirm:
                    raise SystemExit("apply requires --confirm")
                result = await service.apply()
            else:
                result = (await SharePointReadinessService(client, settings).check()).to_dict()
            print(json.dumps(result, indent=2))
        return 0
    finally:
        await client.aclose()
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SharePoint repository bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    apply = sub.add_parser("apply")
    apply.add_argument("--confirm", action="store_true")
    sub.add_parser("verify")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
