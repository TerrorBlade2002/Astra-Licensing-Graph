"""Register the licensing mailbox and its real folders from Graph.

    python -m app.cli.graph_mailbox_bootstrap --mailbox licensing@example.com
    python -m app.cli.graph_mailbox_bootstrap --mailbox licensing@example.com --dry-run

Delta sync and change subscriptions both address a folder by its Graph folder
id. The development seed invents those ids, which is fine for a synthetic
mailbox and useless against a real one — Graph answers 404 for an id it never
issued. This command reads the folder tree and records the ids Graph actually
returned, so ingestion has something valid to point at.

It reads. It creates no subscription, moves no message, and writes nothing to
the mailbox. Folders that have disappeared are reported, never deleted: a
folder row is referenced by sync state and ingested email, and a rename should
not orphan history.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from urllib.parse import quote

from app.core.config import get_settings
from app.core.constants import KNOWN_MAILBOX_FOLDERS
from app.core.logging import configure_logging
from app.graph.client import GraphHttpClient
from app.graph.errors import GraphApiError
from app.models import MailboxFolder
from app.models.mixins import utcnow
from app.repositories.mailboxes import MailboxRepository
from app.workers.context import WorkerContext

#: Workflow folders are commonly nested one level under Inbox. Three levels
#: covers that without walking an archive tree of unbounded depth.
MAX_DEPTH = 3
PAGE_SIZE = 100


async def _folder_page(
    client: GraphHttpClient, url: str, *, first: bool
) -> tuple[list[dict[str, Any]], str | None]:
    # A nextLink already carries the query it was produced from; repeating it
    # would send $top and $select twice.
    params = (
        {"$top": PAGE_SIZE, "$select": "id,displayName,childFolderCount,parentFolderId"}
        if first
        else None
    )
    payload = await client.get_json(url, params=params, operation="list_mail_folders")
    return list(payload.get("value") or []), payload.get("@odata.nextLink")


async def _walk(
    client: GraphHttpClient,
    mailbox_identifier: str,
    *,
    folder_id: str | None = None,
    path_prefix: str = "",
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Every folder at or below ``folder_id``, each with its display path."""
    if depth > MAX_DEPTH:
        return []
    base = f"users/{quote(mailbox_identifier, safe='')}/mailFolders"
    if folder_id:
        base = f"{base}/{folder_id}/childFolders"
    url: str | None = client.build_url(base)

    discovered: list[dict[str, Any]] = []
    first = True
    while url:
        items, next_link = await _folder_page(client, url, first=first)
        first = False
        for item in items:
            name = str(item.get("displayName") or "")
            path = f"{path_prefix}/{name}" if path_prefix else name
            discovered.append(
                {
                    "id": str(item["id"]),
                    "display_name": name,
                    "folder_path": path,
                    "parent_graph_folder_id": item.get("parentFolderId"),
                }
            )
            if int(item.get("childFolderCount") or 0) > 0:
                discovered.extend(
                    await _walk(
                        client,
                        mailbox_identifier,
                        folder_id=str(item["id"]),
                        path_prefix=path,
                        depth=depth + 1,
                    )
                )
        url = client.validate_continuation_url(next_link) if next_link else None
    return discovered


def _permission_hint(error: GraphApiError) -> str | None:
    """Turn the two failures worth explaining into a next action."""
    if error.status_code == 403:
        return (
            "Graph refused the request. The application permission Mail.Read "
            "(or Mail.ReadBasic.All) most likely has not been granted admin consent."
        )
    if error.status_code == 404:
        return (
            "Graph does not know this mailbox. Check the address, and that it is a "
            "mailbox in this tenant rather than a distribution list."
        )
    return None


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.graph_enabled:
        print(json.dumps({"status": "disabled", "detail": "GRAPH_ENABLED is false."}))
        return 1

    address = args.mailbox.strip().lower()
    expected = (settings.graph_expected_mailbox_address or "").strip().lower()
    if expected and address != expected:
        # The deployment is pinned to one mailbox; reading another would be a
        # mistake worth failing on rather than a convenience.
        print(
            json.dumps(
                {
                    "status": "refused",
                    "detail": "Address does not match the configured GRAPH_MAILBOX.",
                }
            )
        )
        return 1

    ctx = WorkerContext.build(settings, worker_id="cli-mailbox-bootstrap")
    try:
        try:
            folders = await _walk(ctx.graph_client, address)
        except GraphApiError as exc:
            print(
                json.dumps(
                    {
                        "status": "graph_error",
                        "status_code": exc.status_code,
                        "graph_error_code": exc.graph_error_code,
                        "hint": _permission_hint(exc),
                    },
                    indent=2,
                )
            )
            return 1

        async with ctx.session_factory() as session:
            repo = MailboxRepository(session)
            mailbox = await repo.get_by_address(address)
            mailbox_created = mailbox is None
            if mailbox is None:
                mailbox = await repo.create(address=address, display_name=args.display_name)

            existing = {row.graph_folder_id: row for row in await repo.list_folders(mailbox.id)}
            now = utcnow()
            created, updated = [], []
            for folder in folders:
                row = existing.get(folder["id"])
                if row is None:
                    session.add(
                        MailboxFolder(
                            mailbox_id=mailbox.id,
                            graph_folder_id=folder["id"],
                            parent_graph_folder_id=folder["parent_graph_folder_id"],
                            display_name=folder["display_name"],
                            folder_path=folder["folder_path"],
                            last_verified_at=now,
                        )
                    )
                    created.append(folder["display_name"])
                    continue
                if (
                    row.display_name != folder["display_name"]
                    or row.folder_path != folder["folder_path"]
                ):
                    updated.append(folder["display_name"])
                row.display_name = folder["display_name"]
                row.folder_path = folder["folder_path"]
                row.parent_graph_folder_id = folder["parent_graph_folder_id"]
                row.last_verified_at = now

            seen = {folder["id"] for folder in folders}
            stale = [row.display_name for key, row in existing.items() if key not in seen]

            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()

            discovered = sorted(folder["folder_path"] for folder in folders)
            found = {name.lower() for folder in folders for name in (folder["display_name"],)}
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "dry_run": args.dry_run,
                        "mailbox": address,
                        "mailbox_created": mailbox_created,
                        "folders_discovered": len(folders),
                        "folders_created": sorted(created),
                        "folders_updated": sorted(updated),
                        "folders_no_longer_present": sorted(stale),
                        "known_workflow_folders_missing": [
                            name for name in KNOWN_MAILBOX_FOLDERS if name.lower() not in found
                        ],
                        "folder_paths": discovered,
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
    parser = argparse.ArgumentParser(description="Discover mailbox folders from Graph.")
    parser.add_argument("--mailbox", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing."
    )
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
