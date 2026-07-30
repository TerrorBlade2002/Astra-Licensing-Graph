"""Controlled form inspection, mapping, preparation, and signature recording."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import ActorDep, SessionDep, SettingsDep
from app.auth.actors import CurrentActor
from app.auth.policies import require_role
from app.auth.roles import Role
from app.licensing.jobs import LicensingJobType
from app.models import FormInstance, FormTemplate, FormTemplateField
from app.repositories.licensing_jobs import LicensingJobRepository
from app.schemas.licensing import (
    ApproveForSignature,
    FormFieldsPatch,
    FormInstanceCreate,
    FormInstanceDetailOut,
    FormTemplateCreate,
    FormTemplateOut,
    MappingUpsert,
    RecordExternalSubmission,
    RecordSignedDocument,
)
from app.services.form_preparation_service import FormPreparationService

router = APIRouter(tags=["form-preparation"])

AnalystDep = Annotated[CurrentActor, Depends(require_role(Role.ANALYST))]
ReviewerDep = Annotated[CurrentActor, Depends(require_role(Role.REVIEWER))]
AdminDep = Annotated[CurrentActor, Depends(require_role(Role.ADMIN))]


class FormGenerateRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    flatten: bool = False


async def _bounded_upload(file: UploadFile, maximum: int) -> bytes:
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        from app.core.exceptions import StateConflictError

        raise StateConflictError("Uploaded form content exceeds the configured maximum.")
    return content


@router.get("/form-templates", response_model=list[FormTemplateOut])
async def list_templates(
    session: SessionDep, actor: ActorDep, status: str | None = None
) -> list[FormTemplate]:
    stmt = select(FormTemplate).order_by(FormTemplate.created_at.desc())
    if status:
        stmt = stmt.where(FormTemplate.status == status)
    return list(await session.scalars(stmt))


@router.post("/form-templates", response_model=FormTemplateOut, status_code=201)
async def create_template(
    payload: FormTemplateCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> FormTemplate:
    return await FormPreparationService(session, settings).register_template(
        actor=actor, **payload.model_dump(exclude_none=True)
    )


@router.post("/form-templates/{template_id}/inspect")
async def inspect_template(
    template_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
    file: UploadFile = File(...),
) -> dict[str, object]:
    content = await _bounded_upload(file, settings.form_max_template_bytes)
    result = await FormPreparationService(session, settings).inspect(
        template_id,
        actor=actor,
        content=content,
        filename=file.filename or "template.bin",
    )
    return {
        "form_format": result.form_format,
        "detection_status": result.detection_status,
        "field_count": result.field_count,
        "notes": result.notes,
        "fields": [
            {
                "field_key": field.field_key,
                "native_field_name": field.native_field_name,
                "label": field.label,
                "field_type": field.field_type,
                "required": field.required,
                "page_number": field.page_number,
            }
            for field in result.fields
        ],
    }


@router.post(
    "/form-templates/{template_id}/activate",
    response_model=FormTemplateOut,
)
async def activate_template(
    template_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> FormTemplate:
    return await FormPreparationService(session, settings).activate_template(
        template_id, actor=actor
    )


@router.post("/form-templates/{template_id}/mappings")
async def upsert_mapping(
    template_id: uuid.UUID,
    payload: MappingUpsert,
    session: SessionDep,
    settings: SettingsDep,
    actor: AdminDep,
) -> dict[str, str]:
    field = await session.scalar(
        select(FormTemplateField).where(
            FormTemplateField.form_template_id == template_id,
            FormTemplateField.field_key == payload.field_key,
        )
    )
    if field is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Template field not found.")
    mapping = await FormPreparationService(session, settings).upsert_mapping(
        field.id,
        actor=actor,
        source_type=payload.source_type,
        source_key=payload.source_key,
        transformation=payload.transformation,
        approve=payload.approve,
    )
    return {"mapping_id": str(mapping.id), "status": mapping.mapping_status}


@router.get("/form-instances")
async def list_instances(
    session: SessionDep,
    actor: ActorDep,
    case_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    stmt = select(FormInstance).order_by(FormInstance.created_at.desc())
    if case_id:
        stmt = stmt.where(FormInstance.compliance_case_id == case_id)
    if status:
        stmt = stmt.where(FormInstance.status == status)
    rows = list(await session.scalars(stmt))
    return [
        {
            "id": str(row.id),
            "instance_key": row.instance_key,
            "compliance_case_id": str(row.compliance_case_id),
            "form_template_id": str(row.form_template_id),
            "version": row.version,
            "status": row.status,
            "signature_required": row.signature_required,
            "signature_status": row.signature_status,
        }
        for row in rows
    ]


@router.post("/compliance-cases/{case_id}/form-instances", status_code=201)
async def create_instance(
    case_id: uuid.UUID,
    payload: FormInstanceCreate,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> dict[str, str]:
    service = FormPreparationService(session, settings)
    instance = await service.create_instance(
        case_id, actor=actor, form_template_id=payload.form_template_id
    )
    await service.prefill(instance.id, actor=actor)
    return {"id": str(instance.id), "status": instance.status}


@router.get("/form-instances/{instance_id}", response_model=FormInstanceDetailOut)
async def get_instance(
    instance_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> dict[str, object]:
    return await FormPreparationService(session, settings).detail(instance_id)


@router.patch("/form-instances/{instance_id}/fields", response_model=FormInstanceDetailOut)
async def set_fields(
    instance_id: uuid.UUID,
    payload: FormFieldsPatch,
    session: SessionDep,
    settings: SettingsDep,
    actor: AnalystDep,
) -> dict[str, object]:
    service = FormPreparationService(session, settings)
    for field in payload.fields:
        await service.set_field(
            instance_id,
            actor=actor,
            field_key=field.field_key,
            value=field.value,
            status=field.status,
            commit=False,
        )
    await session.commit()
    return await service.detail(instance_id)


@router.post("/form-instances/{instance_id}/generate", status_code=202)
async def generate_form(
    instance_id: uuid.UUID,
    payload: FormGenerateRequest,
    session: SessionDep,
    actor: AnalystDep,
) -> dict[str, object]:
    instance = await session.get(FormInstance, instance_id)
    if instance is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Form instance not found.")
    job, created = await LicensingJobRepository(session).enqueue(
        job_type=LicensingJobType.PREPARE_FORM,
        idempotency_key=f"prepare-form:{instance_id}:{payload.idempotency_key}",
        payload={
            "form_instance_id": str(instance_id),
            "flatten": payload.flatten,
            "requested_by_actor": actor.actor_id,
        },
        compliance_case_id=instance.compliance_case_id,
    )
    await session.commit()
    return {"job_id": str(job.id), "created": created, "status": job.status}


@router.get("/form-instances/{instance_id}/worksheet")
async def worksheet(
    instance_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    format: str = "text",
) -> Response:
    content, media_type = await FormPreparationService(session, settings).worksheet(
        instance_id, fmt=format
    )
    extension = "csv" if format == "csv" else "txt"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="form-{instance_id}-worksheet.{extension}"'
            ),
        },
    )


@router.post(
    "/form-instances/{instance_id}/approve-for-signature",
    response_model=FormInstanceDetailOut,
)
async def approve_for_signature(
    instance_id: uuid.UUID,
    payload: ApproveForSignature,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> dict[str, object]:
    service = FormPreparationService(session, settings)
    await service.approve_for_signature(
        instance_id, actor=actor, **payload.model_dump(exclude_none=True)
    )
    return await service.detail(instance_id)


@router.post(
    "/form-instances/{instance_id}/record-signed-document",
    response_model=FormInstanceDetailOut,
)
async def record_signed_document(
    instance_id: uuid.UUID,
    payload: RecordSignedDocument,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> dict[str, object]:
    service = FormPreparationService(session, settings)
    await service.record_signed_document(
        instance_id, actor=actor, **payload.model_dump(exclude_none=True)
    )
    return await service.detail(instance_id)


@router.post(
    "/form-instances/{instance_id}/record-external-submission",
    response_model=FormInstanceDetailOut,
)
async def record_external_submission(
    instance_id: uuid.UUID,
    payload: RecordExternalSubmission,
    session: SessionDep,
    settings: SettingsDep,
    actor: ReviewerDep,
) -> dict[str, object]:
    """Record a human action; this endpoint never contacts a filing portal."""
    service = FormPreparationService(session, settings)
    await service.record_external_submission(instance_id, actor=actor, reference=payload.reference)
    return await service.detail(instance_id)
