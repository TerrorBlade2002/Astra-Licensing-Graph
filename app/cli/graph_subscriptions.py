"""Subscription management CLI.

python -m app.cli.graph_subscriptions list
python -m app.cli.graph_subscriptions ensure --mailbox <address> --folder Inbox
python -m app.cli.graph_subscriptions renew --subscription-id <uuid>
python -m app.cli.graph_subscriptions reconcile --mailbox <address> [--dry-run]
python -m app.cli.graph_subscriptions delete --subscription-id <uuid> --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.enums import GraphSubscriptionStatus
from app.graph.subscriptions import GraphSubscriptionApi
from app.models import GraphSubscription, Mailbox, MailboxFolder
from app.models.mixins import utcnow
from app.repositories.mailboxes import MailboxRepository
from app.services.graph_subscriptions import GraphSubscriptionService
from app.workers.context import WorkerContext


def _sanitize(row: GraphSubscription) -> dict[str, object]:
    return {
        "id": str(row.id),
        "mailbox_id": str(row.mailbox_id),
        "folder_id": str(row.folder_id),
        "graph_subscription_id": row.graph_subscription_id,
        "status": row.status,
        "expiration_at": row.expiration_at.isoformat() if row.expiration_at else None,
        "last_renewed_at": row.last_renewed_at.isoformat() if row.last_renewed_at else None,
        "last_notification_at": (
            row.last_notification_at.isoformat() if row.last_notification_at else None
        ),
        "last_error_code": row.last_error_code,
    }


async def _resolve_folder(
    session: AsyncSession,
    mailbox_address: str,
    folder_name: str,
) -> tuple[Mailbox, MailboxFolder]:
    repo = MailboxRepository(session)
    mailbox = await repo.get_by_address(mailbox_address)
    if mailbox is None:
        raise SystemExit(f"Mailbox not found: {mailbox_address}")
    folders = await repo.list_folders(mailbox.id)
    matches = [f for f in folders if f.display_name.lower() == folder_name.lower()]
    if not matches:
        raise SystemExit(f"Folder not found: {folder_name}")
    return mailbox, matches[0]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    ctx = WorkerContext.build(settings, worker_id="cli-subscriptions")
    try:
        async with ctx.session_factory() as session:
            service = GraphSubscriptionService(
                session, settings, GraphSubscriptionApi(ctx.graph_client)
            )
            if args.command == "list":
                rows = (await session.scalars(select(GraphSubscription))).all()
                print(json.dumps([_sanitize(r) for r in rows], indent=2))
            elif args.command == "ensure":
                mailbox, folder = await _resolve_folder(session, args.mailbox, args.folder)
                row = await service.ensure_subscription(
                    mailbox.id, folder.id, actor_id="cli-ensure"
                )
                await service.ensure_sync_state(mailbox.id, folder.id)
                print(json.dumps(_sanitize(row), indent=2))
            elif args.command == "renew":
                found = await session.get(GraphSubscription, uuid.UUID(args.subscription_id))
                if found is None:
                    raise SystemExit("Subscription not found.")
                result = await service.ensure_subscription(
                    found.mailbox_id, found.folder_id, actor_id="cli-renew"
                )
                print(json.dumps(_sanitize(result), indent=2))
            elif args.command == "reconcile":
                repo = MailboxRepository(session)
                target = await repo.get_by_address(args.mailbox)
                if target is None:
                    raise SystemExit(f"Mailbox not found: {args.mailbox}")
                report = await service.reconcile(
                    target.id,
                    dry_run=args.dry_run,
                    delete_unknown_remote=args.delete_unknown_remote,
                )
                print(json.dumps(report.to_dict(), indent=2))
            elif args.command == "delete":
                if not args.confirm:
                    raise SystemExit("Refusing to delete without --confirm.")
                doomed = await session.get(GraphSubscription, uuid.UUID(args.subscription_id))
                if doomed is None:
                    raise SystemExit("Subscription not found.")
                if doomed.graph_subscription_id:
                    await GraphSubscriptionApi(ctx.graph_client).delete(
                        doomed.graph_subscription_id
                    )
                doomed.status = GraphSubscriptionStatus.REMOVED.value
                doomed.removed_at = utcnow()
                await session.commit()
                print(json.dumps(_sanitize(doomed), indent=2))
        return 0
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)
    parser = argparse.ArgumentParser(description="Graph subscription management.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    ensure = sub.add_parser("ensure")
    ensure.add_argument("--mailbox", required=True)
    ensure.add_argument("--folder", required=True)
    renew = sub.add_parser("renew")
    renew.add_argument("--subscription-id", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--mailbox", required=True)
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--delete-unknown-remote", action="store_true")
    delete_cmd = sub.add_parser("delete")
    delete_cmd.add_argument("--subscription-id", required=True)
    delete_cmd.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
