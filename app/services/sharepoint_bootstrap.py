"""Idempotent, non-destructive site/drive catalog bootstrap."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.documents.metadata import REQUIRED_COLUMNS, discover_column_mapping
from app.models import SharePointDrive, SharePointSite, SharePointSyncState
from app.models.mixins import utcnow
from app.sharepoint.client import SharePointClient


@dataclass(frozen=True)
class BootstrapDrivePlan:
    purpose: str
    graph_drive_id: str | None
    action: str
    display_name: str | None = None
    missing_columns: tuple[str, ...] = ()
    incompatible_columns: tuple[str, ...] = ()


class SharePointBootstrapService:
    def __init__(self, session: AsyncSession, client: SharePointClient, settings: Settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    async def plan(self) -> dict[str, object]:
        site_id = self.settings.sharepoint_site_id
        if not site_id:
            raise ValueError("SHAREPOINT_SITE_ID must be resolved before bootstrap.")
        site = await self.client.get_site(site_id)
        remote = {value.id: value for value in await self.client.list_drives(site_id)}
        entries: list[BootstrapDrivePlan] = []
        for purpose, drive_id in self.settings.sharepoint_drive_ids.items():
            drive = remote.get(drive_id or "")
            missing_columns: tuple[str, ...] = ()
            incompatible_columns: tuple[str, ...] = ()
            if drive and drive.list_id:
                columns = await self.client.list_columns(site_id, drive.list_id)
                mapping, incompatible = discover_column_mapping(columns)
                missing_columns = tuple(sorted(set(REQUIRED_COLUMNS) - set(mapping)))
                incompatible_columns = tuple(incompatible)
            entries.append(
                BootstrapDrivePlan(
                    purpose,
                    drive_id,
                    "upsert" if drive else "missing",
                    drive.name if drive else None,
                    missing_columns,
                    incompatible_columns,
                )
            )
        return {
            "site": {"id": site.id, "display_name": site.display_name, "web_url": site.web_url},
            "drives": [asdict(value) for value in entries],
            "destructive_changes": [],
        }

    async def apply(self) -> dict[str, object]:
        plan = await self.plan()
        drive_plan = cast(list[dict[str, Any]], plan["drives"])
        missing = [value for value in drive_plan if value["action"] == "missing"]
        if missing:
            raise ValueError("Bootstrap cannot apply while configured drives are missing.")
        if any(value["missing_columns"] or value["incompatible_columns"] for value in drive_plan):
            raise ValueError("Administrator-assisted SharePoint column setup is incomplete.")
        site_data = cast(dict[str, Any], plan["site"])
        site = await self.session.scalar(
            select(SharePointSite).where(SharePointSite.graph_site_id == site_data["id"])
        )
        if site is None:
            site = SharePointSite(
                id=uuid.uuid4(),
                graph_site_id=site_data["id"],
                permission_mode=self.settings.sharepoint_permission_mode,
            )
            self.session.add(site)
        site.hostname = self.settings.sharepoint_site_hostname
        site.site_path = self.settings.sharepoint_site_path
        site.display_name = site_data["display_name"]
        site.web_url = site_data["web_url"]
        site.expected_app_id = self.settings.sharepoint_expected_app_id
        site.last_verified_at = utcnow()
        await self.session.flush()
        remote = {value.id: value for value in await self.client.list_drives(site.graph_site_id)}
        for purpose, drive_id in self.settings.sharepoint_drive_ids.items():
            assert drive_id is not None
            info = remote[drive_id]
            row = await self.session.scalar(
                select(SharePointDrive).where(
                    SharePointDrive.site_id == site.id, SharePointDrive.graph_drive_id == drive_id
                )
            )
            if row is None:
                row = SharePointDrive(
                    id=uuid.uuid4(),
                    site_id=site.id,
                    graph_drive_id=drive_id,
                    display_name=info.name,
                    purpose=purpose,
                )
                self.session.add(row)
            root = await self.client.get_drive_root(drive_id)
            row.graph_list_id = info.list_id
            row.root_drive_item_id = root.id
            row.display_name = info.name
            row.drive_type = info.drive_type
            row.web_url = info.web_url
            row.purpose = purpose
            row.is_active = True
            row.last_verified_at = utcnow()
            await self.session.flush()
            state = await self.session.scalar(
                select(SharePointSyncState).where(SharePointSyncState.drive_id == row.id)
            )
            if state is None:
                self.session.add(SharePointSyncState(id=uuid.uuid4(), drive_id=row.id))
        await self.session.commit()
        return plan
