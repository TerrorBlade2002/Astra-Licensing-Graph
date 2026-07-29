"""Governed document catalog, lifecycle, link, and version endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import cast

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep
from app.documents.authorization import DevelopmentDocumentAuthorization
from app.models import Document, DocumentLink, DocumentVersion
from app.repositories.documents import DocumentRepository, DocumentSearch
from app.schemas.document import (
    DocumentDetailOut,
    DocumentEventOut,
    DocumentLinkCreate,
    DocumentLinkOut,
    DocumentListOut,
    DocumentOut,
    DocumentPatch,
    DocumentVersionOut,
)
from app.services.document_catalog import DocumentCatalogService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=DocumentListOut)
async def list_documents(
    session: SessionDep,
    actor: ActorDep,
    document_type: str | None = None,
    lifecycle_status: str | None = None,
    approval_status: str | None = None,
    confidentiality_level: str | None = None,
    legal_entity: str | None = None,
    jurisdiction: str | None = None,
    license_type: str | None = None,
    license_number: str | None = None,
    vendor: str | None = None,
    reusable: bool | None = None,
    approved_for_reuse: bool | None = None,
    expires_before: date | None = None,
    expires_after: date | None = None,
    source_type: str | None = None,
    source_email_id: uuid.UUID | None = None,
    source_task_id: uuid.UUID | None = None,
    filename_contains: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> DocumentListOut:
    policy = DevelopmentDocumentAuthorization()
    rows, total = await DocumentRepository(session).search(
        DocumentSearch(
            document_type=document_type,
            lifecycle_status=lifecycle_status,
            approval_status=approval_status,
            confidentiality_level=confidentiality_level,
            legal_entity=legal_entity,
            jurisdiction=jurisdiction,
            license_type=license_type,
            license_number=license_number,
            vendor=vendor,
            reusable=reusable,
            approved_for_reuse=approved_for_reuse,
            expires_before=expires_before,
            expires_after=expires_after,
            source_type=source_type,
            source_email_id=source_email_id,
            source_task_id=source_task_id,
            filename_contains=filename_contains,
        ),
        page=page,
        page_size=page_size,
        include_restricted=policy.can_manage_repository(actor),
    )
    return DocumentListOut(
        items=[DocumentOut.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetailOut)
async def document_detail(
    document_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> DocumentDetailOut:
    service = DocumentCatalogService(session)
    document = await service.require(document_id)
    if not DevelopmentDocumentAuthorization().can_view_document(actor, document):
        raise HTTPException(status_code=404, detail="Document not found.")
    repo = service.repo
    versions = await repo.versions(document.id)
    current = next((value for value in versions if value.id == document.current_version_id), None)
    return DocumentDetailOut(
        document=DocumentOut.model_validate(document),
        current_version=DocumentVersionOut.model_validate(current) if current else None,
        versions=[DocumentVersionOut.model_validate(value) for value in versions],
        links=[DocumentLinkOut.model_validate(value) for value in await repo.links(document.id)],
        recent_events=[
            DocumentEventOut.model_validate(event) for event in await repo.events(document.id)
        ],
    )


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(
    document_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[DocumentVersion]:
    document = await DocumentCatalogService(session).require(document_id)
    if not DevelopmentDocumentAuthorization().can_view_document(actor, document):
        raise HTTPException(status_code=404, detail="Document not found.")
    return await DocumentRepository(session).versions(document_id)


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionOut)
async def version_detail(
    document_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> DocumentVersion:
    document = await DocumentCatalogService(session).require(document_id)
    if not DevelopmentDocumentAuthorization().can_view_document(actor, document):
        raise HTTPException(status_code=404, detail="Document not found.")
    version = await DocumentRepository(session).version(document_id, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    return version


@router.patch("/{document_id}", response_model=DocumentOut)
async def patch_document(
    document_id: uuid.UUID, body: DocumentPatch, session: SessionDep, actor: ActorDep
) -> Document:
    changes = body.model_dump(exclude={"expected_updated_at"}, exclude_unset=True)
    return await DocumentCatalogService(session).update_metadata(
        document_id,
        changes,
        expected_updated_at=body.expected_updated_at,
        actor_id=actor.actor_id or "unknown",
    )


async def _transition(
    document_id: uuid.UUID, session: SessionDep, actor: ActorDep, method: str
) -> Document:
    service = DocumentCatalogService(session)
    document = await service.require(document_id)
    if not DevelopmentDocumentAuthorization().can_approve_document(actor, document):
        raise HTTPException(status_code=403, detail="Document approval is not permitted.")
    return cast(
        Document,
        await getattr(service, method)(document_id, actor.actor_id or "unknown"),
    )


@router.post("/{document_id}/submit-review", response_model=DocumentOut)
async def submit_review(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "submit_for_review")


@router.post("/{document_id}/approve", response_model=DocumentOut)
async def approve(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "approve")


@router.post("/{document_id}/reject", response_model=DocumentOut)
async def reject(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "reject")


@router.post("/{document_id}/approve-reuse", response_model=DocumentOut)
async def approve_reuse(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "approve_reuse")


@router.post("/{document_id}/revoke-reuse", response_model=DocumentOut)
async def revoke_reuse(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "revoke_reuse")


@router.post("/{document_id}/supersede", response_model=DocumentOut)
async def supersede(document_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> Document:
    return await _transition(document_id, session, actor, "supersede")


@router.post("/{document_id}/links", response_model=DocumentLinkOut, status_code=201)
async def create_link(
    document_id: uuid.UUID, body: DocumentLinkCreate, session: SessionDep, actor: ActorDep
) -> DocumentLink:
    await DocumentCatalogService(session).require(document_id)
    link = DocumentLink(
        id=uuid.uuid4(),
        document_id=document_id,
        link_type=body.link_type,
        linked_entity_id=body.linked_entity_id,
        linked_external_key=body.linked_external_key,
        relationship=body.relationship,
        is_primary=body.is_primary,
        link_metadata=body.metadata,
        created_by_actor=actor.actor_id,
    )
    session.add(link)
    DocumentRepository(session).add_event(
        document_id, "LINKED", actor_type="HUMAN", actor_id=actor.actor_id
    )
    await session.commit()
    return link


@router.delete("/{document_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    document_id: uuid.UUID, link_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> Response:
    link = await session.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document_id, DocumentLink.id == link_id
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Document link not found.")
    await session.delete(link)
    DocumentRepository(session).add_event(
        document_id, "UNLINKED", actor_type="HUMAN", actor_id=actor.actor_id
    )
    await session.commit()
    return Response(status_code=204)
