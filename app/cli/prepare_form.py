"""Generate a governed draft form or a missing-answer worksheet."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.cli.licensing_common import operator_actor, session_scope
from app.core.config import get_settings
from app.services.form_preparation_service import FormPreparationService


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with session_scope() as session:
        service = FormPreparationService(session, get_settings())
        instance_id = uuid.UUID(args.instance_id)
        if args.worksheet:
            content, media_type = await service.worksheet(instance_id, fmt=args.worksheet)
            Path(args.output).write_text(content, encoding="utf-8")
            return {"output": args.output, "media_type": media_type}
        result = await service.generate_draft(
            instance_id,
            actor=operator_actor(args.actor),
            template_content=Path(args.template).read_bytes(),
            flatten=False,
        )
        Path(args.output).write_bytes(result.pop("content"))
        return {"output": args.output, **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--template")
    parser.add_argument("--worksheet", choices=("text", "csv"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--actor", default="operator-cli")
    args = parser.parse_args(argv)
    if not args.worksheet and not args.template:
        parser.error("--template is required unless --worksheet is selected")
    print(json.dumps(asyncio.run(_run(args)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
