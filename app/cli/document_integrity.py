"""Verify one governed document without modifying SharePoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from app.core.config import get_settings
from app.services.document_integrity import DocumentIntegrityService
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext


async def run(document_id: uuid.UUID) -> int:
    settings = get_settings()
    ctx = WorkerContext.build(settings, worker_id="document-integrity")
    client = SharePointClient(ctx.graph_client, settings)
    try:
        async with ctx.session_factory() as session:
            result = await DocumentIntegrityService(session, client).verify(document_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
    finally:
        await client.aclose()
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify document integrity")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--document-id", type=uuid.UUID, required=True)
    args = parser.parse_args(argv)
    return asyncio.run(run(args.document_id))


if __name__ == "__main__":
    sys.exit(main())
