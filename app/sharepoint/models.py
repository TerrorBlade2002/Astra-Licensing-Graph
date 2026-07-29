"""Small typed value objects returned by SharePoint Graph operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SiteInfo:
    id: str
    display_name: str | None
    web_url: str | None

    @classmethod
    def from_graph(cls, value: dict[str, Any]) -> SiteInfo:
        return cls(str(value["id"]), value.get("displayName"), value.get("webUrl"))


@dataclass(frozen=True)
class DriveInfo:
    id: str
    name: str
    drive_type: str | None
    web_url: str | None
    list_id: str | None

    @classmethod
    def from_graph(cls, value: dict[str, Any]) -> DriveInfo:
        list_info = value.get("list") or {}
        return cls(
            id=str(value["id"]),
            name=str(value.get("name") or ""),
            drive_type=value.get("driveType"),
            web_url=value.get("webUrl"),
            list_id=str(list_info["id"]) if list_info.get("id") else None,
        )


@dataclass(frozen=True)
class DriveItemInfo:
    id: str
    name: str
    size: int
    web_url: str | None
    etag: str | None
    ctag: str | None
    parent_id: str | None
    list_item_id: str | None
    is_folder: bool
    raw: dict[str, Any]

    @classmethod
    def from_graph(cls, value: dict[str, Any]) -> DriveItemInfo:
        parent = value.get("parentReference") or {}
        list_item = value.get("listItem") or {}
        return cls(
            id=str(value["id"]),
            name=str(value.get("name") or ""),
            size=int(value.get("size") or 0),
            web_url=value.get("webUrl"),
            etag=value.get("eTag"),
            ctag=value.get("cTag"),
            parent_id=str(parent["id"]) if parent.get("id") else None,
            list_item_id=str(list_item["id"]) if list_item.get("id") else None,
            is_folder="folder" in value,
            raw=value,
        )


@dataclass(frozen=True)
class UploadSessionInfo:
    upload_url: str
    expires_at: datetime | None
    next_expected_offset: int


@dataclass(frozen=True)
class UploadResult:
    item: DriveItemInfo
    method: str
    bytes_written: int
