"""Reconcile one send by immutable Graph ID; never resends."""

import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.services.sent_reconciliation_service import SentReconciliationService
from app.workers.context import WorkerContext


async def run(draft_id: uuid.UUID) -> int:
    context = WorkerContext.build(get_settings())
    try:
        async with context.session_factory() as session:
            row = await SentReconciliationService(
                session, context.settings, context.graph_client
            ).reconcile(draft_id)
            print(f"draft_id={draft_id} send_status={row.status}")
        return 0
    finally:
        await context.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-id", type=uuid.UUID, required=True)
    return asyncio.run(run(parser.parse_args().draft_id))


if __name__ == "__main__":
    raise SystemExit(main())
