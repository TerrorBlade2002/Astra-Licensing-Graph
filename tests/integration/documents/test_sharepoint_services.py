from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.documents.metadata import REQUIRED_COLUMNS
from app.evidence.base import EvidenceWriteResult
from app.evidence.migration import EvidenceMigrationService
from app.models import (
    Document,
    DocumentVersion,
    SharePointDrive,
    SharePointSite,
    SharePointSyncState,
)
from app.services.document_integrity import DocumentIntegrityService
from app.services.document_reconciliation import DocumentReconciliationService
from app.services.sharepoint_bootstrap import SharePointBootstrapService
from app.services.sharepoint_readiness import SharePointReadinessService
from app.sharepoint.models import DriveInfo, DriveItemInfo, SiteInfo, UploadResult
from tests.integration.documents.test_catalog import make_document


def configured_settings(settings: Settings) -> Settings:
    updates = {
        "sharepoint_site_id": "site-1",
        "sharepoint_expected_app_id": "app-1",
        "sharepoint_quarantine_drive_id": "drive-QUARANTINE",
    }
    attributes = {
        "MASTER_DOCUMENTS": "sharepoint_master_documents_drive_id",
        "WORKING_DOCUMENTS": "sharepoint_working_documents_drive_id",
        "BONDS": "sharepoint_bonds_drive_id",
        "SUBMITTED_FILINGS": "sharepoint_submitted_filings_drive_id",
        "LICENSES_CERTIFICATES": "sharepoint_licenses_drive_id",
        "REGULATOR_CORRESPONDENCE": "sharepoint_correspondence_drive_id",
        "PAYMENTS_RECEIPTS": "sharepoint_payments_drive_id",
        "OFFICIAL_FORMS_CHECKLISTS": "sharepoint_forms_drive_id",
    }
    updates.update({attribute: f"drive-{purpose}" for purpose, attribute in attributes.items()})
    return settings.model_copy(update=updates)


class RepositoryFakeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.delta_pages: list[dict] = []
        self.synthetic_deleted = False

    async def get_site(self, site_id: str):
        if site_id == "denied-site":
            raise PermissionError("synthetic selected-site denial")
        return SiteInfo(site_id, "Astra Licensing Compliance", "https://tenant/sites/astra")

    async def resolve_site(self, hostname: str, path: str):
        return SiteInfo("site-1", "Astra", None)

    async def list_drives(self, site_id: str):
        return [
            DriveInfo(drive_id, purpose, "documentLibrary", None, f"list-{purpose}")
            for purpose, drive_id in self.settings.sharepoint_drive_ids.items()
            if drive_id
        ]

    async def get_drive_root(self, drive_id: str):
        return DriveItemInfo("root", "root", 0, None, None, None, None, None, True, {})

    async def list_columns(self, site_id: str, list_id: str):
        return [
            {"displayName": name, "name": name, column_type: {}}
            for name, column_type in REQUIRED_COLUMNS.items()
        ]

    async def drive_delta(self, drive_id: str, continuation_url: str | None = None):
        return self.delta_pages.pop(0)

    async def get_drive_item(self, drive_id: str, item_id: str):
        return DriveItemInfo(
            item_id, "remote.pdf", 999, None, "new-etag", None, "root", None, False, {}
        )

    async def upload_small(self, drive_id, parent_id, filename, data, *, content_type):
        item = DriveItemInfo(
            "synthetic-health", filename, len(data), None, "etag", None, parent_id, None, False, {}
        )
        return UploadResult(item, "simple", len(data))

    async def update_drive_item(self, drive_id, item_id, changes, *, etag=None):
        return await self.get_drive_item(drive_id, item_id)

    async def delete_drive_item(self, drive_id, item_id, *, etag=None):
        self.synthetic_deleted = True


async def test_readiness_and_bootstrap_catalog(
    session: AsyncSession, graph_settings: Settings
) -> None:
    settings = configured_settings(graph_settings)
    fake = RepositoryFakeClient(settings)
    report = await SharePointReadinessService(fake, settings).check()  # type: ignore[arg-type]
    assert report.ready and all(check.ok for check in report.checks)
    service = SharePointBootstrapService(session, fake, settings)  # type: ignore[arg-type]
    plan = await service.plan()
    assert not plan["destructive_changes"]
    await service.apply()
    assert await session.scalar(select(func.count(SharePointDrive.id))) == 9
    assert await session.scalar(select(func.count(SharePointSyncState.id))) == 9
    repeated = await service.apply()
    assert len(repeated["drives"]) == 9  # type: ignore[arg-type]


async def test_readiness_negative_boundary_and_opt_in_write(graph_settings: Settings) -> None:
    settings = configured_settings(graph_settings).model_copy(
        update={
            "sharepoint_negative_test_site_id": "denied-site",
            "sharepoint_enable_write_health_check": True,
        }
    )
    fake = RepositoryFakeClient(settings)
    report = await SharePointReadinessService(fake, settings).check()  # type: ignore[arg-type]
    assert report.ready
    checks = {check.name: check.ok for check in report.checks}
    assert checks["negative_site_boundary"] and checks["synthetic_write"]
    assert fake.synthetic_deleted


async def _repository_drive(session: AsyncSession) -> tuple[SharePointSite, SharePointDrive]:
    site = SharePointSite(
        id=uuid.uuid4(), graph_site_id="site-1", permission_mode="sites_selected", is_active=True
    )
    session.add(site)
    await session.flush()
    drive = SharePointDrive(
        id=uuid.uuid4(),
        site_id=site.id,
        graph_drive_id="drive-1",
        graph_list_id="list-1",
        root_drive_item_id="root",
        display_name="Docs",
        drive_type="documentLibrary",
        purpose="WORKING_DOCUMENTS",
        is_active=True,
    )
    session.add(drive)
    await session.flush()
    return site, drive


async def test_delta_reconciliation_rename_move_delete_and_import(
    session: AsyncSession, graph_settings: Settings
) -> None:
    _site, drive = await _repository_drive(session)
    first, first_version = await make_document(session)
    second, second_version = await make_document(session)
    first_version.graph_drive_id = second_version.graph_drive_id = drive.graph_drive_id
    first_version.graph_drive_item_id = "managed-1"
    second_version.graph_drive_item_id = "managed-2"
    first_version.parent_graph_drive_item_id = "old-parent"
    await session.commit()
    fake = RepositoryFakeClient(graph_settings)
    fake.delta_pages = [
        {
            "value": [
                {
                    "id": "managed-1",
                    "name": "renamed.pdf",
                    "size": 123,
                    "parentReference": {"id": "new-parent"},
                    "eTag": "new",
                },
                {
                    "id": "unknown-1",
                    "name": "existing.pdf",
                    "size": 44,
                    "file": {"mimeType": "application/pdf"},
                    "parentReference": {"id": "root"},
                },
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
        },
        {
            "value": [{"id": "managed-2", "deleted": {"state": "deleted"}}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-token",
        },
    ]
    result = await DocumentReconciliationService(session, fake).reconcile(drive.id)  # type: ignore[arg-type]
    assert result == {"pages": 2, "changes": 3}
    await session.refresh(first)
    await session.refresh(second)
    await session.refresh(first_version)
    assert first.current_filename == "renamed.pdf"
    assert first_version.parent_graph_drive_item_id == "new-parent"
    assert second.lifecycle_status == "DELETED_EXTERNALLY"
    imported = await session.scalar(
        select(Document).where(Document.source_type == "SHAREPOINT_EXISTING")
    )
    assert imported and imported.approval_status == "UNREVIEWED"
    sync = await session.scalar(
        select(SharePointSyncState).where(SharePointSyncState.drive_id == drive.id)
    )
    assert sync and sync.last_page_count == 2 and sync.delta_link is not None


class FakeMigrationStore:
    def __init__(self) -> None:
        self.calls = 0

    async def put_stream(self, key, stream, *, max_bytes, content_type):
        self.calls += 1
        content = b"".join([chunk async for chunk in stream])
        return EvidenceWriteResult(
            storage_uri="sharepoint://site-1/drive-1/item-migrated",
            bytes_written=len(content),
            sha256_checksum=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
            drive_item_id="item-migrated",
            etag="etag",
        )


async def test_evidence_migration_and_integrity(
    session: AsyncSession, tmp_path: Path, graph_settings: Settings
) -> None:
    _site, drive = await _repository_drive(session)
    content = b"governed legacy evidence"
    source = tmp_path / "legacy.pdf"
    source.write_bytes(content)
    document = Document(
        id=uuid.uuid4(),
        document_key="ASTRA-MIGRATE",
        canonical_title="Legacy",
        current_filename="legacy.pdf",
        document_type="OTHER",
        lifecycle_status="ACTIVE",
        approval_status="APPROVED",
        confidentiality_level="INTERNAL",
        reusable=True,
        approved_for_reuse=True,
        content_sha256=hashlib.sha256(content).hexdigest(),
        mime_type="application/pdf",
        size_bytes=len(content),
        source_type="PROTOTYPE_IMPORT",
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        id=uuid.uuid4(),
        document_id=document.id,
        version_number=1,
        graph_site_id="site-1",
        graph_drive_id=drive.graph_drive_id,
        graph_drive_item_id="pending:migration:1",
        filename="legacy.pdf",
        mime_type="application/pdf",
        size_bytes=len(content),
        content_sha256=document.content_sha256,
        storage_status="UPLOADING",
        source_storage_uri=source.as_uri(),
        uploaded_at=document.created_at,
    )
    session.add(version)
    await session.commit()
    store = FakeMigrationStore()
    migration = EvidenceMigrationService(session, store)  # type: ignore[arg-type]
    plan = await migration.plan()
    assert plan.eligible == 1 and plan.estimated_bytes == len(content)
    await migration.run()
    await session.refresh(version)
    assert version.graph_drive_item_id == "item-migrated" and source.exists()
    assert store.calls == 1
    fake = RepositoryFakeClient(graph_settings)
    document.current_version_id = version.id
    version.size_bytes = 10
    version.graph_etag = "old-etag"
    await session.commit()
    result = await DocumentIntegrityService(session, fake).verify(document.id)  # type: ignore[arg-type]
    assert not result["ok"]
    await session.refresh(document)
    assert not document.approved_for_reuse
