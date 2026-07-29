"""Secret-free Sites.Selected and repository readiness reporting."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings
from app.documents.enums import DrivePurpose
from app.documents.metadata import REQUIRED_COLUMNS, discover_column_mapping
from app.sharepoint.client import SharePointClient


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: list[ReadinessCheck]

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "checks": [asdict(value) for value in self.checks]}


class SharePointReadinessService:
    def __init__(self, client: SharePointClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def check(self) -> ReadinessReport:
        checks: list[ReadinessCheck] = []
        site_id = self.settings.sharepoint_site_id
        checks.append(
            ReadinessCheck(
                "expected_application_id",
                bool(self.settings.sharepoint_expected_app_id),
                "Expected application ID is configured."
                if self.settings.sharepoint_expected_app_id
                else "Expected application ID is missing.",
            )
        )
        if not site_id:
            if self.settings.sharepoint_site_hostname and self.settings.sharepoint_site_path:
                site = await self.client.resolve_site(
                    self.settings.sharepoint_site_hostname, self.settings.sharepoint_site_path
                )
                site_id = site.id
            else:
                checks.append(ReadinessCheck("site", False, "Target site is not configured."))
                return ReadinessReport(False, checks)
        try:
            site = await self.client.get_site(site_id)
        except Exception:
            checks.append(
                ReadinessCheck("site_access", False, "Configured site is not accessible.")
            )
            return ReadinessReport(False, checks)
        checks.append(
            ReadinessCheck("site_access", site.id == site_id, "Configured site ID verified.")
        )
        drives = {drive.id: drive for drive in await self.client.list_drives(site_id)}
        for purpose in DrivePurpose:
            configured = self.settings.sharepoint_drive_ids[purpose.value]
            if not configured:
                checks.append(
                    ReadinessCheck(
                        f"drive_{purpose.value.lower()}", False, "Drive ID is not configured."
                    )
                )
                continue
            drive = drives.get(configured)
            checks.append(
                ReadinessCheck(
                    f"drive_{purpose.value.lower()}",
                    bool(drive and drive.drive_type == "documentLibrary"),
                    "Document library verified." if drive else "Configured drive was not found.",
                )
            )
            if drive and drive.list_id:
                columns = await self.client.list_columns(site_id, drive.list_id)
                mapping, incompatible = discover_column_mapping(columns)
                missing = set(REQUIRED_COLUMNS) - set(mapping)
                checks.append(
                    ReadinessCheck(
                        f"columns_{purpose.value.lower()}",
                        not missing and not incompatible,
                        "Required custom columns verified."
                        if not missing and not incompatible
                        else "Required custom columns are missing or incompatible.",
                    )
                )
            else:
                checks.append(
                    ReadinessCheck(
                        f"columns_{purpose.value.lower()}",
                        False,
                        "Backing list ID is unavailable.",
                    )
                )
        quarantine = self.settings.sharepoint_quarantine_drive_id
        checks.append(
            ReadinessCheck(
                "quarantine",
                bool(quarantine and quarantine in drives),
                "Quarantine location verified."
                if quarantine in drives
                else "Quarantine location is missing.",
            )
        )
        if self.settings.sharepoint_negative_test_site_id:
            denied = False
            try:
                await self.client.get_site(self.settings.sharepoint_negative_test_site_id)
            except Exception:
                denied = True
            checks.append(
                ReadinessCheck(
                    "negative_site_boundary",
                    denied,
                    "Unrelated site access was denied."
                    if denied
                    else "Application can access the unrelated negative-test site.",
                )
            )
        if self.settings.sharepoint_enable_write_health_check:
            write_ok = await self._write_health_check(drives)
            checks.append(
                ReadinessCheck(
                    "synthetic_write",
                    write_ok,
                    "Synthetic create/read/update/delete check completed."
                    if write_ok
                    else "Synthetic write check failed; inspect the staging health-check scope.",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    "synthetic_write",
                    True,
                    "Destructive synthetic write check is disabled by default.",
                )
            )
        return ReadinessReport(all(value.ok for value in checks), checks)

    async def _write_health_check(self, drives: dict[str, Any]) -> bool:
        drive_id = self.settings.sharepoint_quarantine_drive_id
        drive = drives.get(drive_id or "")
        if not drive:
            return False
        item = None
        try:
            root = await self.client.get_drive_root(drive.id)
            filename = f"astra-readiness-{uuid.uuid4().hex}.txt"
            uploaded = await self.client.upload_small(
                drive.id, root.id, filename, b"synthetic readiness check", content_type="text/plain"
            )
            item = uploaded.item
            await self.client.get_drive_item(drive.id, item.id)
            await self.client.update_drive_item(
                drive.id,
                item.id,
                {"description": "Astra synthetic readiness check"},
                etag=item.etag,
            )
            return True
        except Exception:
            return False
        finally:
            if item is not None:
                try:
                    await self.client.delete_drive_item(drive.id, item.id)
                except Exception:
                    return False
