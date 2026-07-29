"""Typed SharePoint operations layered on the Milestone 2 Graph client."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.evidence.base import EvidenceStore, EvidenceWriteResult
from app.graph.client import GraphHttpClient
from app.graph.errors import GraphApiError
from app.graph.retry import backoff_delay, is_retryable_status, parse_retry_after
from app.sharepoint.errors import (
    SharePointConcurrencyError,
    SharePointPermissionError,
    UploadProtocolError,
    UploadSessionExpiredError,
)
from app.sharepoint.models import (
    DriveInfo,
    DriveItemInfo,
    SiteInfo,
    UploadResult,
    UploadSessionInfo,
)
from app.sharepoint.urls import validate_upload_url


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_next_expected_offset(values: Sequence[str] | None, total_bytes: int) -> int:
    if not values:
        return total_bytes
    first = values[0].split("-", 1)[0]
    try:
        offset = int(first)
    except ValueError as exc:
        raise UploadProtocolError("Upload session returned an invalid expected range.") from exc
    if offset < 0 or offset > total_bytes:
        raise UploadProtocolError("Upload session returned an out-of-bounds range.")
    return offset


class SharePointClient:
    def __init__(
        self,
        graph: GraphHttpClient,
        settings: Settings,
        *,
        upload_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.graph = graph
        self.settings = settings
        self._owns_upload_client = upload_client is None
        self.upload_client = upload_client or httpx.AsyncClient(
            timeout=settings.sharepoint_upload_timeout_seconds
        )

    async def aclose(self) -> None:
        if self._owns_upload_client:
            await self.upload_client.aclose()

    def _url(self, path: str) -> str:
        return self.graph.build_url(path)

    async def _get(self, path_or_url: str, *, operation: str) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("https://") else self._url(path_or_url)
        try:
            return await self.graph.get_json(url, operation=operation)
        except GraphApiError as exc:
            if exc.status_code == 403:
                raise SharePointPermissionError("SharePoint site access was denied.") from exc
            raise

    async def get_site(self, site_id: str) -> SiteInfo:
        return SiteInfo.from_graph(
            await self._get(f"sites/{quote(site_id, safe=',')}", operation="sharepoint_get_site")
        )

    async def resolve_site(self, hostname: str, site_path: str) -> SiteInfo:
        path = f"sites/{quote(hostname, safe='')}:{quote('/' + site_path.strip('/'), safe='/')}"
        return SiteInfo.from_graph(await self._get(path, operation="sharepoint_resolve_site"))

    async def list_drives(self, site_id: str) -> list[DriveInfo]:
        payload = await self._get(
            f"sites/{quote(site_id, safe=',')}/drives?$expand=list",
            operation="sharepoint_list_drives",
        )
        return [DriveInfo.from_graph(value) for value in payload.get("value", [])]

    async def get_drive(self, drive_id: str) -> DriveInfo:
        payload = await self._get(
            f"drives/{quote(drive_id, safe='')}", operation="sharepoint_get_drive"
        )
        return DriveInfo.from_graph(payload)

    async def get_drive_root(self, drive_id: str) -> DriveItemInfo:
        return DriveItemInfo.from_graph(
            await self._get(
                f"drives/{quote(drive_id, safe='')}/root", operation="sharepoint_get_root"
            )
        )

    async def get_drive_item(self, drive_id: str, item_id: str) -> DriveItemInfo:
        path = f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}?$expand=listItem"
        return DriveItemInfo.from_graph(await self._get(path, operation="sharepoint_get_item"))

    async def list_children(self, drive_id: str, parent_id: str) -> list[DriveItemInfo]:
        payload = await self._get(
            f"drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}/children",
            operation="sharepoint_list_children",
        )
        return [DriveItemInfo.from_graph(value) for value in payload.get("value", [])]

    async def create_folder(self, drive_id: str, parent_id: str, name: str) -> DriveItemInfo:
        url = self._url(
            f"drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}/children"
        )
        payload = await self.graph.post_json(
            url,
            {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
            operation="sharepoint_create_folder",
        )
        return DriveItemInfo.from_graph(payload)

    async def list_columns(self, site_id: str, list_id: str) -> list[dict[str, Any]]:
        payload = await self._get(
            f"sites/{quote(site_id, safe=',')}/lists/{quote(list_id, safe='')}/columns",
            operation="sharepoint_list_columns",
        )
        return list(payload.get("value", []))

    async def get_list_item(self, site_id: str, list_id: str, list_item_id: str) -> dict[str, Any]:
        return await self._get(
            f"sites/{quote(site_id, safe=',')}/lists/{quote(list_id, safe='')}/items/"
            f"{quote(list_item_id, safe='')}?$expand=fields",
            operation="sharepoint_get_list_item",
        )

    async def update_drive_item(
        self, drive_id: str, item_id: str, changes: dict[str, Any], *, etag: str | None = None
    ) -> DriveItemInfo:
        try:
            payload = await self.graph.patch_json(
                self._url(f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"),
                changes,
                headers={"If-Match": etag} if etag else None,
                operation="sharepoint_update_item",
            )
        except GraphApiError as exc:
            if exc.status_code == 412:
                raise SharePointConcurrencyError("SharePoint item changed concurrently.") from exc
            raise
        return DriveItemInfo.from_graph(payload)

    async def delete_drive_item(
        self, drive_id: str, item_id: str, *, etag: str | None = None
    ) -> None:
        await self.graph.delete(
            self._url(f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"),
            headers={"If-Match": etag} if etag else None,
            operation="sharepoint_delete_synthetic_item",
        )

    async def upload_small(
        self, drive_id: str, parent_id: str, filename: str, data: bytes, *, content_type: str
    ) -> UploadResult:
        if len(data) > self.settings.sharepoint_simple_upload_max_bytes:
            raise ValueError("Content exceeds the configured simple-upload limit")
        path = (
            f"drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}:"
            f"/{quote(filename, safe='')}:/content"
        )
        payload = await self.graph.put_bytes(
            self._url(path),
            data,
            headers={"Content-Type": content_type},
            operation="sharepoint_upload_small",
        )
        return UploadResult(DriveItemInfo.from_graph(payload), "simple", len(data))

    async def create_upload_session(
        self, drive_id: str, parent_id: str, filename: str, *, conflict_behavior: str = "fail"
    ) -> UploadSessionInfo:
        path = (
            f"drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}:"
            f"/{quote(filename, safe='')}:/createUploadSession"
        )
        payload = await self.graph.post_json(
            self._url(path),
            {"item": {"@microsoft.graph.conflictBehavior": conflict_behavior, "name": filename}},
            operation="sharepoint_create_upload_session",
        )
        upload_url = validate_upload_url(str(payload.get("uploadUrl") or ""))
        return UploadSessionInfo(
            upload_url=upload_url,
            expires_at=_parse_time(payload.get("expirationDateTime")),
            next_expected_offset=parse_next_expected_offset(payload.get("nextExpectedRanges"), 0),
        )

    async def upload_file_session(
        self, session: UploadSessionInfo, source: Path, *, total_bytes: int
    ) -> UploadResult:
        url = validate_upload_url(session.upload_url)
        offset = session.next_expected_offset
        chunk_size = self.settings.sharepoint_upload_chunk_bytes
        with source.open("rb") as stream:
            stream.seek(offset)
            while offset < total_bytes:
                if session.expires_at and session.expires_at <= datetime.now(UTC):
                    raise UploadSessionExpiredError("The SharePoint upload session expired.")
                chunk = stream.read(min(chunk_size, total_bytes - offset))
                if not chunk:
                    raise UploadProtocolError("Upload source ended before its declared size.")
                end = offset + len(chunk) - 1
                payload, complete = await self._put_range(url, chunk, offset, end, total_bytes)
                if complete:
                    return UploadResult(DriveItemInfo.from_graph(payload), "resumable", total_bytes)
                next_offset = parse_next_expected_offset(
                    payload.get("nextExpectedRanges"), total_bytes
                )
                if next_offset < offset + len(chunk):
                    raise UploadProtocolError("Upload session requested an overlapping byte range.")
                offset = next_offset
                stream.seek(offset)
        raise UploadProtocolError("Upload session ended without a final drive item.")

    async def _put_range(
        self, url: str, data: bytes, start: int, end: int, total: int
    ) -> tuple[dict[str, Any], bool]:
        headers = {
            "Content-Length": str(len(data)),
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Type": "application/octet-stream",
        }
        for attempt in range(1, self.settings.sharepoint_upload_max_attempts + 1):
            response = await self.upload_client.put(url, content=data, headers=headers)
            if response.status_code in (200, 201, 202):
                payload = response.json()
                if not isinstance(payload, dict):
                    raise UploadProtocolError("Upload session returned an invalid response.")
                return payload, response.status_code in (200, 201)
            if response.status_code in (404, 410):
                raise UploadSessionExpiredError("The SharePoint upload session expired.")
            if (
                is_retryable_status(response.status_code)
                and attempt < self.settings.sharepoint_upload_max_attempts
            ):
                await asyncio.sleep(
                    backoff_delay(
                        attempt,
                        max_seconds=self.settings.graph_max_retry_delay_seconds,
                        retry_after=parse_retry_after(response.headers.get("Retry-After")),
                    )
                )
                continue
            raise UploadProtocolError(f"Upload range failed with HTTP {response.status_code}.")
        raise UploadProtocolError("Upload range retry budget exhausted.")

    async def update_list_item_fields(
        self,
        site_id: str,
        list_id: str,
        list_item_id: str,
        fields: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> dict[str, Any]:
        headers = {"If-Match": etag} if etag else None
        try:
            return await self.graph.patch_json(
                self._url(
                    f"sites/{quote(site_id, safe=',')}/lists/{quote(list_id, safe='')}/"
                    f"items/{quote(list_item_id, safe='')}/fields"
                ),
                fields,
                headers=headers,
                operation="sharepoint_update_fields",
            )
        except GraphApiError as exc:
            if exc.status_code == 412:
                raise SharePointConcurrencyError(
                    "SharePoint metadata changed concurrently."
                ) from exc
            raise

    async def list_versions(self, drive_id: str, item_id: str) -> list[dict[str, Any]]:
        payload = await self._get(
            f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/versions",
            operation="sharepoint_list_versions",
        )
        return list(payload.get("value", []))

    async def create_preview(self, drive_id: str, item_id: str) -> dict[str, Any]:
        return await self.graph.post_json(
            self._url(f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/preview"),
            {},
            operation="sharepoint_preview",
        )

    async def drive_delta(
        self, drive_id: str, continuation_url: str | None = None
    ) -> dict[str, Any]:
        path = (
            self.graph.validate_continuation_url(continuation_url)
            if continuation_url
            else f"drives/{quote(drive_id, safe='')}/root/delta"
        )
        return await self._get(path, operation="sharepoint_drive_delta")

    async def download_to_store(
        self, drive_id: str, item_id: str, store: EvidenceStore, key: str, *, max_bytes: int
    ) -> EvidenceWriteResult:
        url = self._url(
            f"drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/content"
        )
        return await self.graph.download_to_store(
            url, store, key, max_bytes=max_bytes, operation="sharepoint_download"
        )

    @staticmethod
    def safe_debug_session(session: UploadSessionInfo) -> str:
        return json.dumps(
            {"expires_at": session.expires_at.isoformat() if session.expires_at else None}
        )
