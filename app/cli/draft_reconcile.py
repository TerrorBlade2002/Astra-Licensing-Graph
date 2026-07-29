"""Reconcile one Graph draft without printing body or recipients."""

import argparse
import asyncio
import uuid

from app.auth.actors import CurrentActor
from app.core.config import get_settings
from app.domain.enums import ActorType
from app.services.graph_draft_service import GraphDraftService
from app.workers.context import WorkerContext


async def run(draft_id: uuid.UUID) -> int:
    context = WorkerContext.build(get_settings())
    actor = CurrentActor(
        actor_type=ActorType.SYSTEM,
        actor_id="draft-reconcile-cli",
        tenant_id="system",
        object_id="draft-reconcile-cli",
    )
    try:
        async with context.session_factory() as session:
            draft, changed = await GraphDraftService(
                session, context.settings, context.graph_client
            ).reconcile(draft_id, actor)
            print(f"draft_id={draft.id} status={draft.draft_status} external_change={changed}")
        return 0
    finally:
        await context.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-id", type=uuid.UUID, required=True)
    return asyncio.run(run(parser.parse_args().draft_id))


if __name__ == "__main__":
    raise SystemExit(main())
