"""CLI: import the PowerShell prototype's JSON records into PostgreSQL.

Usage:
    python -m app.cli.import_prototype --root <path> --mailbox <address> [--dry-run]

Prints a machine-readable JSON report to stdout; logs go to stderr so the
report stays parseable. Email bodies are never written to the console.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.services.prototype_import import PrototypeImporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import PowerShell prototype data.")
    parser.add_argument("--root", required=False, help="Prototype data root directory.")
    parser.add_argument("--mailbox", required=True, help="Shared mailbox address.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing rows.")
    return parser


async def run_import(root: Path, mailbox: str, dry_run: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        importer = PrototypeImporter(session_factory, root, mailbox, dry_run=dry_run)
        report = await importer.run()
    finally:
        await engine.dispose()
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if report.errors and not (report.inserted or report.updated or report.skipped) else 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)
    args = build_parser().parse_args(argv)
    root = Path(args.root or settings.prototype_import_root)
    return asyncio.run(run_import(root, args.mailbox, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
