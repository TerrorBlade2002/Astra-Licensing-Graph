"""Run SharePoint drive reconciliation without exposing delta links."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.models import SharePointDrive
from app.services.document_reconciliation import DocumentReconciliationService
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    ctx = WorkerContext.build(settings, worker_id="document-reconciliation")
    client = SharePointClient(ctx.graph_client, settings)
    try:
        async with ctx.session_factory() as session:
            drive = await session.scalar(
                select(SharePointDrive).where(SharePointDrive.purpose == args.drive_purpose)
            )
            if not drive:
                raise SystemExit("Configured drive purpose was not found.")
            if args.dry_run:
                print(json.dumps({"drive_id": str(drive.id), "would_reconcile": True}))
            else:
                print(
                    json.dumps(
                        await DocumentReconciliationService(session, client).reconcile(drive.id),
                        indent=2,
                    )
                )
        return 0
    finally:
        await client.aclose()
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile or import SharePoint documents")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("import-existing")
    command.add_argument("--drive-purpose", required=True)
    command.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
