"""Report Milestone 6 licensing data-quality findings."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.cli.licensing_common import session_scope
from app.services.licensing_data_quality import LicensingDataQualityService


async def _run() -> dict[str, object]:
    async with session_scope() as session:
        return await LicensingDataQualityService(session).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run",))
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run()), indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
