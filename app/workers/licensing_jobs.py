"""Durable worker for Milestone 6 licensing lifecycle jobs."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.metrics import LICENSING_JOBS_TOTAL
from app.documents.enums import SourceType
from app.domain.enums import ActorType
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.sharepoint import SharePointEvidenceStore
from app.forms.enums import FormFormat
from app.licensing.audit import add_licensing_audit
from app.licensing.jobs import LicensingJobType
from app.models import (
    ComplianceCase,
    ComplianceObligation,
    Document,
    DocumentPacket,
    DocumentVersion,
    FormInstance,
    FormTemplate,
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicensingJob,
    RequirementSourceSnapshot,
)
from app.repositories.licensing_jobs import LicensingJobRepository
from app.services.compliance_case_service import ComplianceCaseService
from app.services.deadline_service import DeadlineService
from app.services.document_catalog import DocumentCatalogService
from app.services.document_packet_service import DocumentPacketService
from app.services.document_upload import DocumentUploadMetadata, DocumentUploadService
from app.services.form_preparation_service import FormPreparationService
from app.services.information_registry_service import InformationRegistryService
from app.services.requirement_assessment_service import RequirementAssessmentService
from app.services.requirement_source_service import RequirementSourceService
from app.services.tracker_import_service import TrackerImportService
from app.sharepoint.client import SharePointClient
from app.sharepoint.urls import parse_sharepoint_storage_uri
from app.workers.context import WorkerContext


def _system_actor(job: LicensingJob) -> CurrentActor:
    actor_id = str(job.payload.get("requested_by_actor") or "licensing-worker")[:200]
    return CurrentActor(
        actor_type=ActorType.SYSTEM,
        actor_id=actor_id,
        tenant_id="internal",
        object_id=actor_id,
        display_name="Licensing worker",
        roles=("Licensing.Admin", "Licensing.Manager", "Licensing.Reviewer"),
        scopes=(),
    )


class LicensingWorkerRunner:
    def __init__(
        self,
        ctx: WorkerContext,
        *,
        job_types: list[LicensingJobType],
        once: bool,
        max_jobs: int | None,
    ) -> None:
        self.ctx = ctx
        self.job_types = job_types
        self.once = once
        self.max_jobs = max_jobs
        self.processed = 0

    async def run(self) -> int:
        while True:
            worked = await self._cycle()
            if (self.once and not worked) or (
                self.max_jobs is not None and self.processed >= self.max_jobs
            ):
                return self.processed
            if not worked:
                await asyncio.sleep(self.ctx.settings.licensing_worker_poll_interval_seconds)

    async def _cycle(self) -> bool:
        async with self.ctx.session_factory() as session:
            repo = LicensingJobRepository(session)
            job = await repo.claim_next(
                worker_id=self.ctx.worker_id,
                lease_seconds=self.ctx.settings.licensing_job_lease_seconds,
                job_types=self.job_types,
            )
            if job is None:
                return False
            try:
                await self._handle(session, job)
                refreshed = await session.get(LicensingJob, job.id)
                if refreshed is not None:
                    await repo.mark_completed(refreshed)
                LICENSING_JOBS_TOTAL.labels(job_type=job.job_type, outcome="completed").inc()
            except Exception as exc:
                await session.rollback()
                refreshed = await session.get(LicensingJob, job.id)
                if refreshed is not None:
                    await repo.record_failure(
                        refreshed,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                        retryable=isinstance(
                            exc, (OSError, httpx.TimeoutException, httpx.TransportError)
                        ),
                    )
                LICENSING_JOBS_TOTAL.labels(job_type=job.job_type, outcome="failed").inc()
            self.processed += 1
            return True

    async def _handle(self, session: AsyncSession, job: LicensingJob) -> None:
        payload = dict(job.payload or {})
        actor = _system_actor(job)
        job_type = LicensingJobType(job.job_type)

        if job_type is LicensingJobType.EVALUATE_REQUIREMENT_ASSESSMENT:
            await RequirementAssessmentService(session, self.ctx.settings).evaluate(
                uuid.UUID(payload["assessment_id"]), actor=actor
            )
            return
        if job_type is LicensingJobType.FETCH_REQUIREMENT_SOURCE:
            snapshot, changed = await RequirementSourceService(
                session, self.ctx.settings
            ).fetch_public_snapshot(
                uuid.UUID(payload["source_id"]),
                actor=actor,
                evidence_store=self.ctx.evidence_store,
            )
            if changed:
                await LicensingJobRepository(session).enqueue(
                    job_type=LicensingJobType.COMPARE_SOURCE_SNAPSHOT,
                    idempotency_key=(f"source-compare:{snapshot.id}:{snapshot.content_sha256}"),
                    payload={
                        "snapshot_id": str(snapshot.id),
                        "requested_by_actor": actor.actor_id,
                    },
                )
                await session.commit()
            return
        if job_type is LicensingJobType.COMPARE_SOURCE_SNAPSHOT:
            snapshot_id = uuid.UUID(payload["snapshot_id"])
            source_service = RequirementSourceService(session, self.ctx.settings)
            comparison = await source_service.diff(snapshot_id)
            compared_snapshot = await session.get(RequirementSourceSnapshot, snapshot_id)
            previous = (
                await session.get(RequirementSourceSnapshot, compared_snapshot.previous_snapshot_id)
                if compared_snapshot and compared_snapshot.previous_snapshot_id
                else None
            )
            if (
                compared_snapshot
                and previous
                and compared_snapshot.extracted_text_storage_uri
                and previous.extracted_text_storage_uri
            ):
                before = (
                    await self._read_controlled_storage_uri(
                        previous.extracted_text_storage_uri,
                        max_bytes=self.ctx.settings.requirement_source_max_bytes,
                    )
                ).decode("utf-8", errors="replace")
                after = (
                    await self._read_controlled_storage_uri(
                        compared_snapshot.extracted_text_storage_uri,
                        max_bytes=self.ctx.settings.requirement_source_max_bytes,
                    )
                ).decode("utf-8", errors="replace")
                compared_snapshot.change_details = {
                    **dict(compared_snapshot.change_details or {}),
                    "text_diff": source_service.text_diff(before, after),
                }
            add_licensing_audit(
                session,
                actor=actor,
                entity_type="requirement_source_snapshot",
                entity_id=snapshot_id,
                action="requirement_source_snapshot_compared",
                after={
                    "hash_changed": comparison["hash_changed"],
                    "affects_rules": comparison["affects_rules"],
                },
            )
            await session.commit()
            return
        if job_type is LicensingJobType.MATERIALIZE_DEADLINES:
            deadline_service = DeadlineService(session, self.ctx.settings)
            if payload.get("obligation_id"):
                await deadline_service.materialize_for_obligation(
                    uuid.UUID(payload["obligation_id"]), actor=actor
                )
            else:
                await deadline_service.materialize_all(actor=actor)
            await deadline_service.refresh_statuses()
            await deadline_service.run_escalations(manager_actor=payload.get("manager_actor"))
            return
        if job_type is LicensingJobType.CHECK_INFORMATION_FRESHNESS:
            await InformationRegistryService(session, self.ctx.settings).expire_stale_values()
            await RequirementSourceService(session, self.ctx.settings).freshness_report(
                notify_owners=True
            )
            return
        if job_type is LicensingJobType.BUILD_DOCUMENT_PACKET:
            packet_id = uuid.UUID(payload["packet_id"])
            packet_service = DocumentPacketService(session, self.ctx.settings)
            packet = await session.get(DocumentPacket, packet_id)
            if packet is None:
                raise ValueError("Document packet not found.")
            if packet.status == "DRAFT" or payload.get("rebuild_manifest"):
                packet = await packet_service.build(
                    packet_id,
                    actor=actor,
                    overrides={
                        key: uuid.UUID(value)
                        for key, value in dict(payload.get("overrides") or {}).items()
                    },
                    commit=False,
                )
            expected_manifest = payload.get("manifest_sha256")
            if expected_manifest and expected_manifest != packet.manifest_sha256:
                raise ValueError(
                    "Packet manifest changed after the archive job was queued; "
                    "a new packet build is required."
                )
            sharepoint = SharePointClient(self.ctx.graph_client, self.ctx.settings)
            await packet_service.generate_archive(
                packet_id,
                actor=actor,
                sharepoint=sharepoint,
                evidence_store=self.ctx.evidence_store,
            )
            return
        if job_type is LicensingJobType.GENERATE_FORM_WORKSHEET:
            instance_id = uuid.UUID(payload["form_instance_id"])
            content, media_type = await FormPreparationService(
                session, self.ctx.settings
            ).worksheet(
                instance_id,
                fmt=str(payload.get("format") or "text"),
            )
            extension = "csv" if media_type == "text/csv" else "txt"
            await self._store_generated_form_document(
                session,
                instance_id=instance_id,
                actor=actor,
                content=content.encode("utf-8"),
                filename=f"field-worksheet.{extension}",
                mime_type=media_type,
                worksheet=True,
            )
            return
        if job_type is LicensingJobType.PREPARE_FORM:
            instance_id = uuid.UUID(payload["form_instance_id"])
            instance = await session.get(FormInstance, instance_id)
            if instance is None:
                raise ValueError("Form instance not found.")
            if instance.generated_document_id:
                return
            template = await session.get(FormTemplate, instance.form_template_id)
            if template is None:
                raise ValueError("Form template not found.")
            temp_root, source_path, _document = await self._download_governed_document(
                session,
                template.template_document_id,
                max_bytes=self.ctx.settings.form_max_template_bytes,
            )
            try:
                result = await FormPreparationService(session, self.ctx.settings).generate_draft(
                    instance_id,
                    actor=actor,
                    template_content=source_path.read_bytes(),
                    flatten=bool(payload.get("flatten", False)),
                    commit=False,
                )
                extension = "docx" if template.form_format == FormFormat.DOCX.value else "pdf"
                mime_type = (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if extension == "docx"
                    else "application/pdf"
                )
                await self._store_generated_form_document(
                    session,
                    instance_id=instance_id,
                    actor=actor,
                    content=result["content"],
                    filename=f"prepared-form.{extension}",
                    mime_type=mime_type,
                    worksheet=False,
                )
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
            return
        if job_type is LicensingJobType.IMPORT_MASTER_TRACKER:
            source_document_id = uuid.UUID(payload["source_document_id"])
            temp_root, source_path, document = await self._download_governed_document(
                session,
                source_document_id,
                max_bytes=self.ctx.settings.tracker_import_max_bytes,
            )
            try:
                await TrackerImportService(session, self.ctx.settings).plan(
                    actor=actor,
                    filename=document.current_filename,
                    content=source_path.read_bytes(),
                    mapping=dict(payload.get("mapping") or {}) or None,
                    sheet_name=payload.get("sheet_name"),
                    source_document_id=document.id,
                )
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
            return
        if job_type is LicensingJobType.CREATE_COMPLIANCE_CASE:
            await ComplianceCaseService(session, self.ctx.settings).open_case(
                uuid.UUID(payload["obligation_id"]),
                actor=actor,
                assigned_owner=payload.get("assigned_owner"),
            )
            return
        if job_type is LicensingJobType.CREATE_NEXT_OBLIGATION:
            await ComplianceCaseService(session, self.ctx.settings).create_next_obligation(
                uuid.UUID(payload["obligation_id"]), actor=actor
            )
            return
        if job_type is LicensingJobType.CHECK_DOCUMENT_EXPIRY:
            await DocumentCatalogService(session).mark_expired()
            return
        if job_type is LicensingJobType.CHECK_LICENSE_RENEWALS:
            obligations = list(
                await session.scalars(
                    select(ComplianceObligation.id).where(
                        ComplianceObligation.status.in_(("PLANNED", "ACTIVE"))
                    )
                )
            )
            deadline_service = DeadlineService(session, self.ctx.settings)
            case_service = ComplianceCaseService(session, self.ctx.settings)
            for obligation_id in obligations:
                created = await deadline_service.materialize_for_obligation(
                    obligation_id, actor=actor, commit=False
                )
                if created:
                    await case_service.open_case(obligation_id, actor=actor, commit=False)
            await session.commit()
            return

        raise ValueError(f"Unsupported licensing job type: {job_type.value}")

    async def _download_governed_document(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        *,
        max_bytes: int,
    ) -> tuple[Path, Path, Document]:
        """Download one pinned current version and verify its catalogue hashes."""
        document = await session.get(Document, document_id)
        version = (
            await session.get(DocumentVersion, document.current_version_id)
            if document and document.current_version_id
            else None
        )
        if (
            document is None
            or version is None
            or document.lifecycle_status != "ACTIVE"
            or document.approval_status != "APPROVED"
            or version.storage_status != "AVAILABLE"
        ):
            raise ValueError("The governed source document is not approved and available.")
        temp_root = Path(tempfile.mkdtemp(prefix="astra-licensing-source-"))
        local_store = FilesystemEvidenceStore(temp_root)
        sharepoint = SharePointClient(self.ctx.graph_client, self.ctx.settings)
        try:
            result = await sharepoint.download_to_store(
                version.graph_drive_id,
                version.graph_drive_item_id,
                local_store,
                "source",
                max_bytes=max_bytes,
            )
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
        expected = version.content_sha256.lower()
        if (
            result.sha256_checksum.lower() != expected
            or document.content_sha256.lower() != expected
        ):
            shutil.rmtree(temp_root, ignore_errors=True)
            raise ValueError("The governed source document failed SHA-256 verification.")
        return temp_root, temp_root / "source", document

    async def _read_controlled_storage_uri(self, uri: str, *, max_bytes: int) -> bytes:
        """Read a governed artifact without accepting arbitrary HTTP URLs."""
        parsed = urlsplit(uri)
        if parsed.scheme == "sharepoint":
            _site_id, drive_id, item_id = parse_sharepoint_storage_uri(uri)
            temp_root = Path(tempfile.mkdtemp(prefix="astra-source-comparison-"))
            local_store = FilesystemEvidenceStore(temp_root)
            try:
                await SharePointClient(self.ctx.graph_client, self.ctx.settings).download_to_store(
                    drive_id,
                    item_id,
                    local_store,
                    "content",
                    max_bytes=max_bytes,
                )
                return await local_store.open("content")
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
        if parsed.scheme == "file" and self.ctx.settings.evidence_storage_backend == "filesystem":
            raw_path = unquote(parsed.path)
            if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                raw_path = raw_path[1:]
            path = Path(raw_path).resolve()
            root = Path(self.ctx.settings.filesystem_evidence_root).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("Local evidence URI is outside the controlled root.")
            if path.stat().st_size > max_bytes:
                raise ValueError("Controlled artifact exceeds its configured size limit.")
            return path.read_bytes()
        raise ValueError("Only governed SharePoint or local-test storage URIs are accepted.")

    async def _store_generated_form_document(
        self,
        session: AsyncSession,
        *,
        instance_id: uuid.UUID,
        actor: CurrentActor,
        content: bytes,
        filename: str,
        mime_type: str,
        worksheet: bool,
    ) -> None:
        """Upload a generated artifact and bind it to its form instance."""
        if not isinstance(self.ctx.evidence_store, SharePointEvidenceStore):
            raise ValueError(
                "Generated form documents require the governed SharePoint evidence backend."
            )
        instance = await session.get(FormInstance, instance_id)
        case = await session.get(ComplianceCase, instance.compliance_case_id) if instance else None
        entity = await session.get(LegalEntity, case.legal_entity_id) if case else None
        licence = (
            await session.get(LicenseInventory, case.license_id)
            if case and case.license_id
            else None
        )
        jurisdiction = await session.get(Jurisdiction, licence.jurisdiction_id) if licence else None
        if instance is None or case is None or entity is None:
            raise ValueError("The form instance scope is incomplete.")
        temp_root = Path(tempfile.mkdtemp(prefix="astra-generated-form-"))
        output = temp_root / filename
        try:
            output.write_bytes(content)
            upload = DocumentUploadService(
                session,
                self.ctx.evidence_store,
                allowed_mime_types=self.ctx.settings.document_allowed_mime_types,
                allowed_extensions=self.ctx.settings.document_allowed_extensions,
                max_bytes=self.ctx.settings.document_max_bytes,
                filename_max_length=self.ctx.settings.document_filename_max_length,
            )
            outcome = await upload.upload_path(
                output,
                original_filename=filename,
                mime_type=mime_type,
                metadata=DocumentUploadMetadata(
                    canonical_title=(
                        f"{'Field worksheet' if worksheet else 'Prepared form'} "
                        f"for {instance.instance_key}"
                    ),
                    document_type=("FORM_FIELD_WORKSHEET" if worksheet else "PREPARED_FORM_DRAFT"),
                    legal_entity=entity.legal_name,
                    jurisdiction=jurisdiction.name if jurisdiction else None,
                    confidentiality_level="CONFIDENTIAL",
                    reusable=False,
                ),
                source_type=SourceType.GENERATED_FORM,
                actor_id=actor.actor_id,
                idempotency_key=(
                    f"form:{instance.id}:{'worksheet' if worksheet else 'draft'}:"
                    f"{hashlib.sha256(content).hexdigest()}"
                ),
                links=[("FILING", instance.id, None, "GENERATED_FORM_ARTIFACT")],
            )
            if worksheet:
                instance.worksheet_document_id = outcome.document.id
            else:
                instance.generated_document_id = outcome.document.id
            await session.commit()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
