"""Build or inspect an immutable document packet manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.document_packet_service import DocumentPacketService


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with session_scope() as session:
        service = DocumentPacketService(session, get_settings())
        packet_id = uuid.UUID(args.packet_id)
        if args.build:
            await service.build(packet_id, actor=operator_actor(args.actor))
        return await service.detail(packet_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
