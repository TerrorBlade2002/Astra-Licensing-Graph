from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import DocumentJobType
from app.models import Document, DocumentVersion
from app.models.mixins import utcnow
from app.repositories.document_jobs import DocumentJobRepository
from app.repositories.documents import DocumentRepository
from app.services.document_catalog import DocumentCatalogService


async def make_document(session: AsyncSession, *, restricted: bool = False, expired: bool = False):
    document = Document(
        id=uuid.uuid4(),
        document_key=f"ASTRA-{uuid.uuid4().hex}",
        canonical_title="Colorado License",
        current_filename="Astra_CO_License.pdf",
        document_type="ISSUED_LICENSE",
        lifecycle_status="ACTIVE",
        approval_status="PENDING_REVIEW",
        confidentiality_level="RESTRICTED" if restricted else "INTERNAL",
        jurisdiction="Colorado",
        reusable=True,
        approved_for_reuse=False,
        content_sha256="a" * 64,
        mime_type="application/pdf",
        size_bytes=123,
        source_type="MANUAL_UPLOAD",
        expiry_date=date.today() - timedelta(days=1)
        if expired
        else date.today() + timedelta(days=30),
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        id=uuid.uuid4(),
        document_id=document.id,
        version_number=1,
        graph_site_id="site",
        graph_drive_id="drive",
        graph_drive_item_id=f"item-{uuid.uuid4().hex}",
        filename=document.current_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        content_sha256=document.content_sha256,
        storage_status="AVAILABLE",
        uploaded_at=utcnow(),
    )
    session.add(version)
    await session.flush()
    document.current_version_id = version.id
    await session.commit()
    return document, version


async def test_approval_reuse_expiry_and_events(session: AsyncSession) -> None:
    document, _version = await make_document(session)
    service = DocumentCatalogService(session)
    await service.approve(document.id, "reviewer")
    approved = await service.approve_reuse(document.id, "reviewer")
    assert approved.approved_for_reuse
    approved.expiry_date = date.today() - timedelta(days=1)
    await session.commit()
    assert await service.mark_expired() == 1
    await session.refresh(approved)
    assert approved.lifecycle_status == "EXPIRED" and not approved.approved_for_reuse
    assert {
        event.event_type for event in await DocumentRepository(session).events(document.id)
    } >= {"APPROVED", "REUSE_APPROVED", "EXPIRED"}


async def test_document_key_link_and_job_idempotency(session: AsyncSession) -> None:
    document, _version = await make_document(session)
    duplicate = Document(
        id=uuid.uuid4(),
        document_key=document.document_key,
        canonical_title="duplicate",
        current_filename="d.pdf",
        document_type="OTHER",
        lifecycle_status="ACTIVE",
        approval_status="UNREVIEWED",
        confidentiality_level="INTERNAL",
        reusable=False,
        approved_for_reuse=False,
        content_sha256="b" * 64,
        size_bytes=1,
        source_type="MANUAL_UPLOAD",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    repo = DocumentJobRepository(session)
    first, created = await repo.enqueue(
        job_type=DocumentJobType.RECONCILE_DRIVE, idempotency_key="same-job"
    )
    second, created_again = await repo.enqueue(
        job_type=DocumentJobType.RECONCILE_DRIVE, idempotency_key="same-job"
    )
    assert created and not created_again and first.id == second.id
