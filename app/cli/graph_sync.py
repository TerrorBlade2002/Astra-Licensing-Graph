"""Folder-sync CLI: enqueue jobs and inspect sync state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.service import GraphJobService
from app.models import MailboxSyncState
from app.repositories.mailboxes import MailboxRepository
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    ctx = WorkerContext.build(settings, worker_id="cli-sync")
    try:
        async with ctx.session_factory() as session:
            repo = MailboxRepository(session)
            mailbox = await repo.get_by_address(args.mailbox)
            if mailbox is None:
                raise SystemExit(f"Mailbox not found: {args.mailbox}")
            folders = await repo.list_folders(mailbox.id)
            matches = [f for f in folders if f.display_name.lower() == args.folder.lower()]
            if not matches:
                raise SystemExit(f"Folder not found: {args.folder}")
            folder = matches[0]

            if args.command == "enqueue":
                jobs = GraphJobService(session, settings)
                result = await jobs.enqueue_sync_folder(
                    mailbox_id=mailbox.id,
                    folder_id=folder.id,
                    reason=args.reason,
                )
                await session.commit()
                print(
                    json.dumps(
                        {
                            "job_id": str(result.job.id),
                            "created": result.created,
                            "coalesced": result.coalesced,
                            "status": result.job.status,
                        },
                        indent=2,
                    )
                )
            elif args.command == "status":
                state = await session.scalar(
                    select(MailboxSyncState).where(
                        MailboxSyncState.mailbox_id == mailbox.id,
                        MailboxSyncState.folder_id == folder.id,
                    )
                )
                if state is None:
                    print(json.dumps({"status": "no_sync_state"}))
                else:
                    print(
                        json.dumps(
                            {
                                "has_delta_link": state.delta_link is not None,
                                "delta_url_fingerprint": state.last_delta_url_fingerprint,
                                "needs_rebaseline": state.needs_rebaseline,
                                "last_started_at": (
                                    state.last_started_at.isoformat()
                                    if state.last_started_at
                                    else None
                                ),
                                "last_completed_at": (
                                    state.last_completed_at.isoformat()
                                    if state.last_completed_at
                                    else None
                                ),
                                "last_page_count": state.last_page_count,
                                "last_change_count": state.last_change_count,
                                "last_error_code": state.last_error_code,
                                "lease_owner": state.lease_owner,
                            },
                            indent=2,
                        )
                    )
        return 0
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)
    parser = argparse.ArgumentParser(description="Folder delta sync operations.")
    sub = parser.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--mailbox", required=True)
    enqueue.add_argument("--folder", required=True)
    enqueue.add_argument("--reason", default="MANUAL")
    status = sub.add_parser("status")
    status.add_argument("--mailbox", required=True)
    status.add_argument("--folder", required=True)
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
