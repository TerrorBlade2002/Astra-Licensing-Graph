"""Document packet assembly, validation, approval, and immutability."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import PACKET_BUILDS_TOTAL, PACKET_MISSING_ITEMS_TOTAL
from app.deadlines.alerts import missing_document_alert
from app.evidence.base import EvidenceStore
from app.evidence.filesystem import FilesystemEvidenceStore
from app.licensing.audit import add_licensing_audit, record_notification
from app.models import (
    ComplianceCase,
    Document,
    DocumentPacket,
    DocumentPacketItem,
    DocumentVersion,
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicenseType,
    PacketTemplate,
    PacketTemplateItem,
)
from app.models.mixins import utcnow
from app.packets.enums import (
    IMMUTABLE_PACKET_STATUSES,
    PacketItemStatus,
    PacketStatus,
    PacketValidationCode,
)
from app.packets.manifests import (
    ManifestEntry,
    OmittedEntry,
    build_archive,
    build_manifest,
    manifest_sha256,
    render_cover_sheet,
    safe_filename,
    unique_filename,
)
from app.packets.matching import (
    CandidateDocument,
    ItemRequirement,
    MatchContext,
    match_all,
)
from app.sharepoint.client import SharePointClient


class DocumentPacketService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _candidates(self, legal_entity: LegalEntity) -> list[CandidateDocument]:
        """Load repository documents belonging to one legal entity.

        Filtering by entity here is defence in depth: the matcher checks entity
        scope again, so a document can only enter a packet if both agree.
        """
        rows = (
            await self.session.execute(
                select(Document, DocumentVersion).outerjoin(
                    DocumentVersion, DocumentVersion.id == Document.current_version_id
                )
            )
        ).all()
        candidates: list[CandidateDocument] = []
        for document, version in rows:
            candidates.append(
                CandidateDocument(
                    document_id=document.id,
                    document_version_id=version.id if version else None,
                    document_type=document.document_type,
                    canonical_title=document.canonical_title,
                    filename=document.current_filename,
                    content_sha256=document.content_sha256,
                    version_sha256=version.content_sha256 if version else None,
                    lifecycle_status=document.lifecycle_status,
                    approval_status=document.approval_status,
                    confidentiality_level=document.confidentiality_level,
                    storage_status=version.storage_status if version else "MISSING",
                    legal_entity=document.legal_entity,
                    jurisdiction=document.jurisdiction,
                    license_type=document.license_type,
                    issue_date=document.issue_date,
                    effective_date=document.effective_date,
                    expiry_date=document.expiry_date,
                    approved_at=document.approved_at,
                    reusable=document.reusable,
                    approved_for_reuse=document.approved_for_reuse,
                    is_current_version=version is not None,
                    size_bytes=document.size_bytes,
                    storage_uri=(
                        f"graph://{version.graph_drive_id}/{version.graph_drive_item_id}"
                        if version
                        else None
                    ),
                )
            )
        return candidates

    async def create_packet(
        self,
        case_id: uuid.UUID,
        *,
        actor: CurrentActor,
        packet_template_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> DocumentPacket:
        """Create the next packet version for a case."""
        case = await self.session.get(ComplianceCase, case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        if not self.settings.packet_generation_enabled:
            raise StateConflictError("Packet generation is disabled by configuration.")
        template = (
            await self.session.get(PacketTemplate, packet_template_id)
            if packet_template_id
            else None
        )
        if packet_template_id and template is None:
            raise NotFoundError("Packet template not found.")
        if template and template.status != "ACTIVE":
            raise StateConflictError("Only an active packet template can create a packet.")
        licence = (
            await self.session.get(LicenseInventory, case.license_id) if case.license_id else None
        )
        if template and licence:
            if template.jurisdiction_id and template.jurisdiction_id != licence.jurisdiction_id:
                raise StateConflictError("The packet template belongs to a different jurisdiction.")
            if template.license_type_id and template.license_type_id != licence.license_type_id:
                raise StateConflictError("The packet template belongs to a different license type.")
        if template and template.case_type and template.case_type != case.case_type:
            raise StateConflictError("The packet template belongs to a different case type.")

        highest = (
            await self.session.scalar(
                select(func.max(DocumentPacket.version)).where(
                    DocumentPacket.compliance_case_id == case_id
                )
            )
            or 0
        )
        packet = DocumentPacket(
            packet_key=f"{case.case_key}-packet-{highest + 1}",
            compliance_case_id=case_id,
            packet_template_id=packet_template_id,
            version=highest + 1,
            status=PacketStatus.DRAFT.value,
            created_by_actor=actor.actor_id,
        )
        self.session.add(packet)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="document_packet",
            entity_id=packet.id,
            action="packet_created",
            after={"version": packet.version},
        )
        if commit:
            await self.session.commit()
        return packet

    async def build(
        self,
        packet_id: uuid.UUID,
        *,
        actor: CurrentActor,
        overrides: dict[str, uuid.UUID] | None = None,
        commit: bool = True,
    ) -> DocumentPacket:
        """Match documents, record items, and produce a manifest.

        An approved packet is never rebuilt: it is an immutable snapshot, so a
        change requires a new version.
        """
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        if packet.status in IMMUTABLE_PACKET_STATUSES:
            raise StateConflictError(
                f"A {packet.status} packet is immutable. Create a new packet version instead."
            )
        case = await self.session.get(ComplianceCase, packet.compliance_case_id)
        if case is None:
            raise NotFoundError("Compliance case not found.")
        entity = await self.session.get(LegalEntity, case.legal_entity_id)
        if entity is None:
            raise NotFoundError("Legal entity not found.")

        licence = (
            await self.session.get(LicenseInventory, case.license_id) if case.license_id else None
        )
        jurisdiction = (
            await self.session.get(Jurisdiction, licence.jurisdiction_id) if licence else None
        )
        license_type = (
            await self.session.get(LicenseType, licence.license_type_id) if licence else None
        )
        packet_template = (
            await self.session.get(PacketTemplate, packet.packet_template_id)
            if packet.packet_template_id
            else None
        )

        template_items = (
            list(
                await self.session.scalars(
                    select(PacketTemplateItem)
                    .where(PacketTemplateItem.packet_template_id == packet.packet_template_id)
                    .order_by(PacketTemplateItem.sort_order)
                )
            )
            if packet.packet_template_id
            else []
        )
        if not template_items:
            raise StateConflictError(
                "The packet has no checklist. Attach a packet template with items first."
            )

        requirements = [
            ItemRequirement(
                item_key=item.item_key,
                document_type=item.document_type,
                required=item.required,
                selection_policy=dict(item.selection_policy or {}),
                sort_order=item.sort_order,
                instructions=item.instructions,
            )
            for item in template_items
        ]
        # A manual override pins a specific document for one item.
        if overrides:
            requirements = [
                (
                    ItemRequirement(
                        item_key=r.item_key,
                        document_type=r.document_type,
                        required=r.required,
                        selection_policy={
                            **r.selection_policy,
                            "document_id": str(overrides[r.item_key]),
                        },
                        sort_order=r.sort_order,
                        instructions=r.instructions,
                    )
                    if r.item_key in overrides
                    else r
                )
                for r in requirements
            ]

        context = MatchContext(
            legal_entity_key=entity.entity_key,
            legal_entity_name=entity.legal_name,
            jurisdiction_key=jurisdiction.jurisdiction_key if jurisdiction else None,
            jurisdiction_name=jurisdiction.name if jurisdiction else None,
            license_type_key=license_type.license_type_key if license_type else None,
            license_type_name=license_type.name if license_type else None,
            today=utcnow().date(),
        )
        results = match_all(requirements, await self._candidates(entity), context)

        # Replace prior items: a rebuild reflects current repository state.
        for existing in list(
            await self.session.scalars(
                select(DocumentPacketItem).where(DocumentPacketItem.document_packet_id == packet.id)
            )
        ):
            await self.session.delete(existing)
        await self.session.flush()

        included: list[ManifestEntry] = []
        missing: list[OmittedEntry] = []
        omitted: list[OmittedEntry] = []
        validations: list[dict[str, Any]] = []
        taken_names: set[str] = set()
        total_bytes = 0

        for index, result in enumerate(results, start=1):
            document = result.document
            filename = None
            if result.is_included and document is not None:
                filename = unique_filename(
                    safe_filename(f"{index:02d}-{document.filename}"), taken_names
                )
                total_bytes += document.size_bytes
                included.append(
                    ManifestEntry(
                        item_key=result.item_key,
                        document_type=result.document_type,
                        document_id=str(document.document_id),
                        document_version_id=(
                            str(document.document_version_id)
                            if document.document_version_id
                            else None
                        ),
                        filename_in_archive=filename,
                        source_filename=document.filename,
                        sha256=document.content_sha256,
                        size_bytes=document.size_bytes,
                        effective_date=(
                            document.effective_date.isoformat() if document.effective_date else None
                        ),
                        expiry_date=(
                            document.expiry_date.isoformat() if document.expiry_date else None
                        ),
                        sort_order=result.sort_order,
                    )
                )
            else:
                entry = OmittedEntry(
                    item_key=result.item_key,
                    document_type=result.document_type,
                    required=result.required,
                    status=result.status,
                    reason=result.inclusion_reason or "No eligible document.",
                )
                if result.required:
                    missing.append(entry)
                else:
                    omitted.append(entry)
                for rejection in result.rejections:
                    validations.append(
                        {
                            "item_key": result.item_key,
                            "code": rejection.code,
                            "detail": rejection.detail,
                        }
                    )

            self.session.add(
                DocumentPacketItem(
                    document_packet_id=packet.id,
                    packet_item_key=result.item_key,
                    document_type=result.document_type,
                    document_id=document.document_id if result.is_included and document else None,
                    document_version_id=(
                        document.document_version_id if result.is_included and document else None
                    ),
                    status=(
                        PacketItemStatus.MATCHED.value if result.is_included else result.status
                    ),
                    inclusion_reason=result.inclusion_reason,
                    document_sha256=(
                        document.content_sha256 if result.is_included and document else None
                    ),
                    filename_in_archive=filename,
                    required=result.required,
                    override_by_actor=(
                        actor.actor_id if overrides and result.item_key in overrides else None
                    ),
                    sort_order=result.sort_order,
                )
            )

        if len(included) > self.settings.packet_max_documents:
            validations.append(
                {
                    "code": PacketValidationCode.PACKET_TOO_MANY_DOCUMENTS.value,
                    "detail": f"{len(included)} documents exceeds the configured maximum.",
                }
            )
        if total_bytes > self.settings.packet_max_total_bytes:
            validations.append(
                {
                    "code": PacketValidationCode.PACKET_TOO_LARGE.value,
                    "detail": f"{total_bytes} bytes exceeds the configured maximum.",
                }
            )

        manifest = build_manifest(
            packet_key=packet.packet_key,
            version=packet.version,
            case_key=case.case_key,
            legal_entity_name=entity.legal_name,
            jurisdiction_name=jurisdiction.name if jurisdiction else None,
            license_type_name=license_type.name if license_type else None,
            template_key=packet_template.template_key if packet_template else None,
            included=included,
            omitted=omitted,
            missing=missing,
            created_by_actor=actor.actor_id,
        )
        packet.manifest = manifest
        packet.manifest_sha256 = manifest_sha256(manifest)
        packet.missing_items = [entry.to_payload() for entry in missing]
        packet.validation_results = validations
        packet.built_at = utcnow()
        packet.status = (
            PacketStatus.MISSING_ITEMS.value
            if missing or any(v.get("code", "").startswith("PACKET_") for v in validations)
            else PacketStatus.READY_FOR_REVIEW.value
        )
        if self.settings.packet_include_cover_sheet:
            packet.cover_sheet_storage_uri = None  # rendered on download

        PACKET_BUILDS_TOTAL.inc()
        if missing:
            PACKET_MISSING_ITEMS_TOTAL.inc(len(missing))
            if case.assigned_owner:
                await record_notification(
                    self.session,
                    missing_document_alert(
                        packet_id=packet.id,
                        compliance_case_id=case.id,
                        recipient_actor=case.assigned_owner,
                        missing_count=len(missing),
                    ),
                )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="document_packet",
            entity_id=packet.id,
            action="packet_built",
            after={
                "status": packet.status,
                "included": len(included),
                "missing": len(missing),
                "manifest_sha256": packet.manifest_sha256,
            },
        )
        if commit:
            await self.session.commit()
        return packet

    async def approve(
        self,
        packet_id: uuid.UUID,
        *,
        actor: CurrentActor,
        allow_missing_optional: bool = True,
        commit: bool = True,
    ) -> DocumentPacket:
        """Approve a packet as ready for the next operational step.

        Approval transmits nothing. It freezes the snapshot.
        """
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        if packet.status in IMMUTABLE_PACKET_STATUSES:
            raise StateConflictError(f"The packet is already {packet.status}.")
        if packet.status == PacketStatus.DRAFT.value:
            raise StateConflictError("Build the packet before approving it.")
        if packet.missing_items:
            raise StateConflictError(
                "Required items are missing. Supply them or override the item first.",
                details={"missing_items": packet.missing_items},
            )
        if self.settings.packet_archive_format == "ZIP" and (
            not packet.archive_storage_uri or not packet.archive_sha256
        ):
            raise StateConflictError(
                "The governed packet archive has not finished generating. "
                "Wait for the packet worker before approval."
            )
        blocking = [
            v
            for v in (packet.validation_results or [])
            if v.get("code")
            in (
                PacketValidationCode.PACKET_TOO_LARGE.value,
                PacketValidationCode.PACKET_TOO_MANY_DOCUMENTS.value,
                PacketValidationCode.DOCUMENT_HASH_MISMATCH.value,
            )
        ]
        if blocking:
            raise StateConflictError(
                "The packet has blocking validation findings.", details={"findings": blocking}
            )
        if packet.reviewed_by_actor and packet.reviewed_by_actor == actor.actor_id:
            pass  # re-approval by the same reviewer is permitted

        packet.status = PacketStatus.APPROVED.value
        packet.reviewed_by_actor = actor.actor_id
        packet.approved_at = utcnow()
        previous_packets = list(
            await self.session.scalars(
                select(DocumentPacket).where(
                    DocumentPacket.compliance_case_id == packet.compliance_case_id,
                    DocumentPacket.id != packet.id,
                    DocumentPacket.status == PacketStatus.APPROVED.value,
                )
            )
        )
        for previous in previous_packets:
            previous.status = PacketStatus.SUPERSEDED.value
            previous.superseded_by_packet_id = packet.id
        # Mark items as included so the manifest and rows agree.
        for item in await self.session.scalars(
            select(DocumentPacketItem).where(
                DocumentPacketItem.document_packet_id == packet.id,
                DocumentPacketItem.status == PacketItemStatus.MATCHED.value,
            )
        ):
            item.status = PacketItemStatus.INCLUDED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="document_packet",
            entity_id=packet.id,
            action="packet_approved",
            after={"manifest_sha256": packet.manifest_sha256, "version": packet.version},
        )
        if commit:
            await self.session.commit()
        return packet

    async def generate_archive(
        self,
        packet_id: uuid.UUID,
        *,
        actor: CurrentActor,
        sharepoint: SharePointClient,
        evidence_store: EvidenceStore,
        commit: bool = True,
    ) -> DocumentPacket:
        """Retrieve pinned versions, recheck hashes, and persist a governed ZIP.

        This is worker-only work: no temporary Graph URL is returned or stored,
        and every included byte is checked against both the immutable packet item
        and its governed document-version digest.
        """
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        if not packet.manifest or not packet.manifest_sha256:
            raise StateConflictError("Build the packet manifest before generating its archive.")
        if packet.status not in (
            PacketStatus.READY_FOR_REVIEW.value,
            PacketStatus.APPROVED.value,
        ):
            raise StateConflictError(
                f"A packet in {packet.status} status cannot produce an archive."
            )

        manifest = dict(packet.manifest)
        items = list(
            await self.session.scalars(
                select(DocumentPacketItem)
                .where(
                    DocumentPacketItem.document_packet_id == packet.id,
                    DocumentPacketItem.status.in_(
                        (PacketItemStatus.MATCHED.value, PacketItemStatus.INCLUDED.value)
                    ),
                )
                .order_by(DocumentPacketItem.sort_order)
            )
        )
        if not items:
            raise StateConflictError("The packet contains no included documents.")

        temp_root = Path(tempfile.mkdtemp(prefix="astra-packet-build-"))
        local_store = FilesystemEvidenceStore(temp_root)
        archive_files: dict[str, bytes] = {}
        try:
            for item in items:
                if not item.document_id or not item.document_version_id:
                    raise StateConflictError(
                        f"Packet item {item.packet_item_key} has no pinned document version."
                    )
                document = await self.session.get(Document, item.document_id)
                version = await self.session.get(DocumentVersion, item.document_version_id)
                if (
                    document is None
                    or version is None
                    or version.document_id != document.id
                    or document.lifecycle_status != "ACTIVE"
                    or document.approval_status != "APPROVED"
                    or version.storage_status != "AVAILABLE"
                ):
                    raise StateConflictError(
                        f"Packet item {item.packet_item_key} is no longer an approved, "
                        "active, available governed version."
                    )
                key = f"items/{item.id}"
                await sharepoint.download_to_store(
                    version.graph_drive_id,
                    version.graph_drive_item_id,
                    local_store,
                    key,
                    max_bytes=min(
                        self.settings.document_download_max_bytes,
                        self.settings.packet_max_total_bytes,
                    ),
                )
                content = await local_store.open(key)
                digest = hashlib.sha256(content).hexdigest()
                expected = (item.document_sha256 or "").lower()
                if not expected or digest != expected or digest != version.content_sha256.lower():
                    packet.validation_results = [
                        *(packet.validation_results or []),
                        {
                            "item_key": item.packet_item_key,
                            "code": PacketValidationCode.DOCUMENT_HASH_MISMATCH.value,
                            "detail": "Retrieved bytes differ from the pinned packet snapshot.",
                        },
                    ]
                    raise StateConflictError(
                        f"Hash verification failed for packet item {item.packet_item_key}."
                    )
                if not item.filename_in_archive:
                    raise StateConflictError(
                        f"Packet item {item.packet_item_key} has no safe archive filename."
                    )
                archive_files[item.filename_in_archive] = content

            archive, archive_sha256 = build_archive(
                manifest=manifest,
                files=archive_files,
                cover_sheet=(
                    render_cover_sheet(manifest)
                    if self.settings.packet_include_cover_sheet
                    else None
                ),
            )
            if len(archive) > self.settings.packet_max_total_bytes:
                raise StateConflictError("Generated packet archive exceeds the configured limit.")
            stored = await evidence_store.put_bytes(
                f"licensing/packets/{packet.packet_key}/{packet.manifest_sha256}.zip",
                archive,
                content_type="application/zip",
            )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        packet.archive_storage_uri = stored.storage_uri
        packet.archive_sha256 = archive_sha256
        packet.archive_size_bytes = len(archive)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="document_packet",
            entity_id=packet.id,
            action="packet_archive_generated",
            after={
                "manifest_sha256": packet.manifest_sha256,
                "archive_sha256": packet.archive_sha256,
                "archive_size_bytes": packet.archive_size_bytes,
            },
        )
        if commit:
            await self.session.commit()
        return packet

    async def reject(
        self, packet_id: uuid.UUID, *, actor: CurrentActor, reason: str, commit: bool = True
    ) -> DocumentPacket:
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        if packet.status in IMMUTABLE_PACKET_STATUSES:
            raise StateConflictError(f"A {packet.status} packet cannot be rejected.")
        packet.status = PacketStatus.REJECTED.value
        packet.rejection_reason = reason[:1000]
        packet.reviewed_by_actor = actor.actor_id
        if commit:
            await self.session.commit()
        return packet

    async def render_cover_sheet(self, packet_id: uuid.UUID) -> str:
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        if not packet.manifest:
            raise StateConflictError("Build the packet before rendering a cover sheet.")
        return render_cover_sheet(dict(packet.manifest))

    async def detail(self, packet_id: uuid.UUID) -> dict[str, Any]:
        packet = await self.session.get(DocumentPacket, packet_id)
        if packet is None:
            raise NotFoundError("Packet not found.")
        items = list(
            await self.session.scalars(
                select(DocumentPacketItem)
                .where(DocumentPacketItem.document_packet_id == packet.id)
                .order_by(DocumentPacketItem.sort_order)
            )
        )
        return {
            "id": str(packet.id),
            "packet_key": packet.packet_key,
            "compliance_case_id": str(packet.compliance_case_id),
            "version": packet.version,
            "status": packet.status,
            "manifest_sha256": packet.manifest_sha256,
            "archive_sha256": packet.archive_sha256,
            "archive_size_bytes": packet.archive_size_bytes,
            "archive_format": self.settings.packet_archive_format,
            "archive_ready": (
                self.settings.packet_archive_format == "NONE" or bool(packet.archive_storage_uri)
            ),
            "missing_items": packet.missing_items,
            "validation_results": packet.validation_results,
            "created_by_actor": packet.created_by_actor,
            "reviewed_by_actor": packet.reviewed_by_actor,
            "approved_at": packet.approved_at.isoformat() if packet.approved_at else None,
            "built_at": packet.built_at.isoformat() if packet.built_at else None,
            "items": [
                {
                    "packet_item_key": item.packet_item_key,
                    "document_type": item.document_type,
                    "document_id": str(item.document_id) if item.document_id else None,
                    "document_version_id": (
                        str(item.document_version_id) if item.document_version_id else None
                    ),
                    "status": item.status,
                    "required": item.required,
                    "inclusion_reason": item.inclusion_reason,
                    "document_sha256": item.document_sha256,
                    "filename_in_archive": item.filename_in_archive,
                    "override_by_actor": item.override_by_actor,
                    "sort_order": item.sort_order,
                }
                for item in items
            ],
        }
