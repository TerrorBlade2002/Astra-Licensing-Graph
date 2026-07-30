"""Reconcile migrated licensing data against the approved source counts.

    python -m app.cli.migration_reconcile totals
    python -m app.cli.migration_reconcile check --expected expected-counts.json

``check`` exits non-zero when any expected total does not match, so it can gate
the go-live checklist instead of relying on someone reading the output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.cli.licensing_common import session_scope
from app.services.migration_reconciliation import MigrationReconciliationService


async def _run(expected: dict[str, int] | None) -> dict[str, object]:
    async with session_scope() as session:
        result = await MigrationReconciliationService(session).reconcile(expected)
        return result.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("totals", help="Print live totals only.")
    check = sub.add_parser("check", help="Compare live totals with an expected-counts file.")
    check.add_argument(
        "--expected",
        required=True,
        help="JSON file mapping reconciliation keys to the counts taken from the source files.",
    )
    args = parser.parse_args(argv)

    expected: dict[str, int] | None = None
    if args.command == "check":
        raw = json.loads(Path(args.expected).read_text("utf-8"))
        expected = {str(key): int(value) for key, value in raw.items()}

    report = asyncio.run(_run(expected))
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("matched", True) else 1


if __name__ == "__main__":
    sys.exit(main())
