"""Reconcile an ambiguous source move without issuing another move."""

import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.services.source_move_service import SourceMoveService
from app.workers.context import WorkerContext


async def run(email_id: uuid.UUID) -> int:
    context = WorkerContext.build(get_settings())
    try:
        async with context.session_factory() as session:
            row = await SourceMoveService(
                session, context.settings, context.graph_client
            ).reconcile(email_id)
            print(f"email_id={email_id} move_status={row.status}")
        return 0
    finally:
        await context.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email-id", type=uuid.UUID, required=True)
    return asyncio.run(run(parser.parse_args().email_id))


if __name__ == "__main__":
    raise SystemExit(main())
