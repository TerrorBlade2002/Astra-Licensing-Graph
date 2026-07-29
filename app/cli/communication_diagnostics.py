"""Sanitized communication configuration and mailbox-scope diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import quote

from sqlalchemy import select

from app.core.config import get_settings
from app.graph.errors import GraphApiError
from app.models import Mailbox, MailboxFolder
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.command == "config":
        print(
            json.dumps(
                {
                    "communications_enabled": settings.communications_enabled,
                    "graph_draft_creation_enabled": settings.graph_draft_creation_enabled,
                    "graph_send_enabled": settings.graph_send_enabled,
                    "graph_message_move_enabled": settings.graph_message_move_enabled,
                    "send_approval_required": settings.communication_require_send_approval,
                    "separate_approver_required": (
                        settings.communication_require_separate_send_approver
                    ),
                    "reply_all_enabled": settings.communication_reply_all_enabled,
                    "bcc_enabled": settings.communication_bcc_enabled,
                    "large_attachments_accepted": (
                        settings.communication_shared_mailbox_large_attachment_accepted
                    ),
                },
                indent=2,
            )
        )
        return 0
    context = WorkerContext.build(settings)
    try:
        if args.command == "scope-denial":
            try:
                await context.graph_client.get_json(
                    context.graph_client.build_url(f"users/{quote(args.mailbox, safe='')}"),
                    params={"$select": "id"},
                    operation="communication_scope_denial_probe",
                )
            except GraphApiError as exc:
                if exc.status_code != 403:
                    print(
                        json.dumps(
                            {
                                "unrelated_mailbox_access": "INCONCLUSIVE",
                                "http_status": exc.status_code,
                            },
                            indent=2,
                        )
                    )
                    return 2
                print(
                    json.dumps(
                        {
                            "unrelated_mailbox_access": "DENIED",
                            "http_status": exc.status_code,
                        },
                        indent=2,
                    )
                )
                return 0
            print(
                json.dumps(
                    {"unrelated_mailbox_access": "UNEXPECTEDLY_SUCCEEDED"},
                    indent=2,
                )
            )
            return 2
        async with context.session_factory() as session:
            mailbox = await session.scalar(
                select(Mailbox).where(Mailbox.address == args.mailbox.lower())
            )
            if mailbox is None:
                raise SystemExit("Configured mailbox was not found.")
            if args.command == "mailbox":
                folders = list(
                    await session.scalars(
                        select(MailboxFolder).where(MailboxFolder.mailbox_id == mailbox.id)
                    )
                )
                print(
                    json.dumps(
                        {
                            "mailbox_configured": True,
                            "graph_user_id_configured": bool(mailbox.graph_user_id),
                            "sent_items_configured": any(
                                row.display_name.lower() == "sent items" for row in folders
                            ),
                            "task_destinations": sum(
                                row.purpose == "TASK_DESTINATION" for row in folders
                            ),
                        },
                        indent=2,
                    )
                )
                return 0
            await context.graph_client.get_json(
                context.graph_client.build_url(
                    f"users/{quote(mailbox.graph_user_id or mailbox.address, safe='')}"
                ),
                params={"$select": "id,mail"},
                operation="communication_permission_probe",
            )
            print(
                json.dumps(
                    {
                        "mail_readwrite_runtime_probe": "SUCCEEDED",
                        "mail_send_runtime_probe": "NOT_SENT_FOR_SAFETY",
                        "mail_send_verification": (
                            "Verify Entra application permission and Exchange RBAC scope using "
                            "the administrator runbook; this diagnostic never sends mail."
                        ),
                    },
                    indent=2,
                )
            )
            return 0
    finally:
        await context.aclose()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("config")
    for name in ("mailbox", "permissions"):
        command = sub.add_parser(name)
        command.add_argument("--mailbox", required=True)
    denial = sub.add_parser("scope-denial")
    denial.add_argument(
        "--mailbox",
        required=True,
        help="Unrelated synthetic mailbox expected to be denied by Exchange RBAC.",
    )
    return result


def main() -> int:
    return asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
