"""Diagnostics CLI. Never prints tokens, secrets, clientState, or delta links."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging, redact_database_url
from app.graph.auth import MsalConfidentialClientTokenProvider
from app.repositories.mailboxes import MailboxRepository
from app.workers.context import WorkerContext


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()

    if args.command == "config":
        print(
            json.dumps(
                {
                    "app_env": settings.app_env,
                    "graph_enabled": settings.graph_enabled,
                    "graph_base_url": settings.graph_base_url,
                    "graph_credential_mode": settings.graph_credential_mode,
                    "graph_tenant_configured": bool(settings.graph_tenant_id),
                    "graph_client_configured": bool(settings.graph_client_id),
                    "graph_secret_configured": bool(settings.graph_client_secret),
                    "public_base_url": settings.public_base_url,
                    "notification_path": settings.graph_notification_path,
                    "lifecycle_path": settings.graph_lifecycle_path,
                    "evidence_backend": settings.evidence_storage_backend,
                    "database": redact_database_url(settings.database_url),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "token":
        provider = MsalConfidentialClientTokenProvider(settings)
        try:
            token = await provider.get_access_token()
        except Exception as exc:
            print(json.dumps({"status": "failed", "error_code": getattr(exc, "error_code", None)}))
            return 1
        # --no-print-token is accepted for interface parity, but the token is
        # never printed regardless: only its length is reported.
        print(json.dumps({"status": "acquired", "token_length": len(token)}))
        return 0

    if args.command == "mailbox":
        ctx = WorkerContext.build(settings, worker_id="cli-diagnostics")
        try:
            async with ctx.session_factory() as session:
                repo = MailboxRepository(session)
                mailbox = await repo.get_by_address(args.mailbox)
                if mailbox is None:
                    print(json.dumps({"status": "not_found"}))
                    return 1
                folders = await repo.list_folders(mailbox.id)
                print(
                    json.dumps(
                        {
                            "status": "ok",
                            "mailbox_id": str(mailbox.id),
                            "graph_user_id_configured": bool(mailbox.graph_user_id),
                            "folders": [f.display_name for f in folders],
                        },
                        indent=2,
                    )
                )
            return 0
        finally:
            await ctx.aclose()
    return 2


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_env)
    parser = argparse.ArgumentParser(description="Graph diagnostics (secret-safe).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config")
    token = sub.add_parser("token")
    token.add_argument("--no-print-token", action="store_true", default=True)
    mailbox = sub.add_parser("mailbox")
    mailbox.add_argument("--mailbox", required=True)
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
