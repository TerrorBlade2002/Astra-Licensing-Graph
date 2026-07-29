from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.documents.metadata import REQUIRED_COLUMNS
from app.evidence.sharepoint import SharePointEvidenceStore
from app.graph.client import GraphHttpClient
from app.models import (
    DocumentLink,
    EmailAttachment,
    SharePointDrive,
    SharePointSite,
)
from app.services.document_catalog import DocumentCatalogService
from app.services.document_promotion import DocumentPromotionService
from app.services.document_upload import DocumentUploadMetadata, DocumentUploadService
from app.sharepoint.client import SharePointClient
from tests.conftest import create_email, create_mailbox


@respx.mock
async def test_attachment_promotion_approval_and_reuse_without_mail_mutation(
    session: AsyncSession,
    tmp_path: Path,
    graph_client: GraphHttpClient,
    graph_settings: Settings,
) -> None:
    mailbox = await create_mailbox(session)
    email = await create_email(session, mailbox, processing_state="ATTACHMENTS_SAVED")
    source = tmp_path / "license.pdf"
    source.write_bytes(b"%PDF-1.7 synthetic licensing evidence")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    attachment = EmailAttachment(
        id=uuid.uuid4(),
        email_id=email.id,
        graph_attachment_id="attachment-1",
        original_filename="Colorado License.pdf",
        stored_filename="license.pdf",
        mime_type="application/pdf",
        stored_size_bytes=source.stat().st_size,
        storage_uri=source.as_uri(),
        sha256_checksum=digest,
        status="DOWNLOADED",
        downloaded_at=datetime.now(UTC),
    )
    site = SharePointSite(
        id=uuid.uuid4(),
        graph_site_id="site-1",
        permission_mode="sites_selected",
        is_active=True,
    )
    drive = SharePointDrive(
        id=uuid.uuid4(),
        site_id=site.id,
        graph_drive_id="drive-1",
        graph_list_id="list-1",
        root_drive_item_id="root-1",
        display_name="Licenses and Certificates",
        drive_type="documentLibrary",
        purpose="LICENSES_CERTIFICATES",
        is_active=True,
    )
    session.add_all([attachment, site])
    await session.flush()
    session.add(drive)
    await session.commit()

    base = graph_settings.graph_base_url
    upload = respx.put(url__regex=rf"{base}/drives/drive-1/items/root-1:/.+:/content").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "item-1",
                "name": "governed.pdf",
                "size": source.stat().st_size,
                "eTag": "etag-1",
                "cTag": "ctag-1",
                "webUrl": "https://tenant.sharepoint.com/item-1",
                "listItem": {"id": "list-item-1"},
            },
        )
    )
    columns = [
        {"displayName": name, "name": f"internal_{name}", column_type: {}}
        for name, column_type in REQUIRED_COLUMNS.items()
    ]
    respx.get(f"{base}/sites/site-1/lists/list-1/columns").mock(
        return_value=httpx.Response(200, json={"value": columns})
    )
    fields = respx.patch(f"{base}/sites/site-1/lists/list-1/items/list-item-1/fields").mock(
        return_value=httpx.Response(200, json={})
    )
    client = SharePointClient(graph_client, graph_settings)
    store = SharePointEvidenceStore(client, site_id="site-1")
    uploader = DocumentUploadService(
        session,
        store,
        allowed_mime_types=["application/pdf"],
        allowed_extensions=[".pdf"],
        max_bytes=1024 * 1024,
        filename_max_length=180,
    )
    try:
        outcome = await DocumentPromotionService(session, uploader).promote(
            attachment.id,
            metadata=DocumentUploadMetadata(
                canonical_title="Colorado Collection Agency License",
                document_type="ISSUED_LICENSE",
                legal_entity="Astra Global",
                jurisdiction="Colorado",
                license_type="Collection Agency License",
                license_number="CO-SYNTHETIC-1",
            ),
            actor_id="reviewer",
            idempotency_key="promotion-synthetic-1",
        )
        assert not outcome.duplicate and upload.called and fields.called
        assert outcome.version and outcome.version.storage_status == "AVAILABLE"
        links = list(
            (
                await session.scalars(
                    select(DocumentLink).where(DocumentLink.document_id == outcome.document.id)
                )
            ).all()
        )
        assert {link.link_type for link in links} == {"EMAIL", "EMAIL_ATTACHMENT"}
        catalog = DocumentCatalogService(session)
        await catalog.approve(outcome.document.id, "reviewer")
        reused = await catalog.approve_reuse(outcome.document.id, "reviewer")
        assert reused.approval_status == "APPROVED" and reused.approved_for_reuse
        await session.refresh(email)
        assert email.processing_state == "ATTACHMENTS_SAVED"
        assert source.exists()
        assert all(call.request.method in {"GET", "PUT", "PATCH"} for call in respx.calls)
    finally:
        await client.aclose()
