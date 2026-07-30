"""Reusable information registry: definitions, versioned values, approval, reuse.

Encryption is applied on write for anything above INTERNAL, bound to the value's
own row. Reads return masked display values unless the caller explicitly asks to
reveal and holds the authority to do so — and every reveal is audited.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.auth.roles import Role, has_role
from app.core.config import Settings
from app.core.crypto import (
    EncryptionUnavailableError,
    SensitiveValueCipher,
    build_cipher,
    content_sha256,
    redact,
)
from app.core.exceptions import DomainError, NotFoundError, StateConflictError
from app.core.metrics import INFORMATION_VALUES_STALE
from app.information_registry.enums import (
    InformationValueStatus,
    ReusablePolicy,
    Sensitivity,
    UsagePurpose,
    ValueFreshness,
)
from app.information_registry.scoping import (
    UsageContext,
    ValueScope,
    assess_freshness,
    evaluate_reuse,
    requires_encryption,
)
from app.information_registry.validation import validate_value
from app.licensing.audit import add_licensing_audit
from app.models import (
    InformationDefinition,
    InformationOwnerAssignment,
    InformationValue,
    InformationValueUsage,
)
from app.models.mixins import utcnow

_ENTITY_TYPE = "information_value"


class SensitiveAccessDeniedError(DomainError):
    code = "sensitive_access_denied"
    http_status = 403


class InformationRegistryService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self._cipher: SensitiveValueCipher | None = None

    def _get_cipher(self) -> SensitiveValueCipher:
        if self._cipher is None:
            try:
                self._cipher = build_cipher(self.settings.information_encryption_key_reference)
            except EncryptionUnavailableError as exc:
                raise StateConflictError(
                    "Sensitive information cannot be stored because no encryption key "
                    "material is configured (INFORMATION_ENCRYPTION_KEYS)."
                ) from exc
        return self._cipher

    # --------------------------------------------------------------- definitions
    async def create_definition(
        self, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> InformationDefinition:
        key = fields["information_key"]
        existing = await self.session.scalar(
            select(InformationDefinition).where(InformationDefinition.information_key == key)
        )
        if existing:
            raise StateConflictError(f"Information key {key!r} already exists.")
        sensitivity = fields.get("sensitivity") or Sensitivity.INTERNAL.value
        if (
            sensitivity == Sensitivity.HIGHLY_RESTRICTED.value
            and not self.settings.information_highly_restricted_enabled
        ):
            raise StateConflictError(
                "HIGHLY_RESTRICTED definitions require INFORMATION_HIGHLY_RESTRICTED_ENABLED."
            )
        definition = InformationDefinition(
            information_key=key,
            name=fields["name"],
            category=fields["category"],
            description=fields.get("description"),
            data_type=fields["data_type"],
            sensitivity=sensitivity,
            default_owner_role=fields.get("default_owner_role"),
            validation_rules=fields.get("validation_rules") or {},
            reusable_policy=fields.get("reusable_policy") or ReusablePolicy.ENTITY_ONLY.value,
            freshness_days=fields.get("freshness_days")
            or self.settings.information_default_freshness_days,
            display_keep_last=int(fields.get("display_keep_last") or 0),
        )
        self.session.add(definition)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="information_definition",
            entity_id=definition.id,
            action="information_definition_created",
            after={"information_key": key, "sensitivity": sensitivity},
        )
        if commit:
            await self.session.commit()
        return definition

    async def assign_owner(
        self,
        definition_id: uuid.UUID,
        *,
        actor: CurrentActor,
        owner_actor: str,
        legal_entity_id: uuid.UUID | None = None,
        is_primary: bool = False,
        commit: bool = True,
    ) -> InformationOwnerAssignment:
        definition = await self.session.get(InformationDefinition, definition_id)
        if definition is None:
            raise NotFoundError("Information definition not found.")
        existing = await self.session.scalar(
            select(InformationOwnerAssignment).where(
                InformationOwnerAssignment.information_definition_id == definition_id,
                InformationOwnerAssignment.legal_entity_id == legal_entity_id,
                InformationOwnerAssignment.owner_actor == owner_actor,
            )
        )
        if existing is not None:
            existing.is_active = True
            existing.is_primary = is_primary
            if commit:
                await self.session.commit()
            return existing
        assignment = InformationOwnerAssignment(
            information_definition_id=definition_id,
            legal_entity_id=legal_entity_id,
            owner_actor=owner_actor,
            is_primary=is_primary,
            assigned_by_actor=actor.actor_id,
        )
        self.session.add(assignment)
        await self.session.flush()
        if commit:
            await self.session.commit()
        return assignment

    # -------------------------------------------------------------------- values
    async def propose_value(
        self,
        *,
        actor: CurrentActor,
        information_definition_id: uuid.UUID,
        value: Any,
        legal_entity_id: uuid.UUID | None = None,
        jurisdiction_id: uuid.UUID | None = None,
        license_id: uuid.UUID | None = None,
        vendor_organization_id: uuid.UUID | None = None,
        compliance_case_id: uuid.UUID | None = None,
        valid_from: date | None = None,
        valid_to: date | None = None,
        owner_actor: str | None = None,
        source_document_id: uuid.UUID | None = None,
        source_reference: str | None = None,
        commit: bool = True,
    ) -> InformationValue:
        """Create a DRAFT value version. Nothing is reusable until approved."""
        definition = await self.session.get(InformationDefinition, information_definition_id)
        if definition is None:
            raise NotFoundError("Information definition not found.")

        issues = validate_value(
            value, data_type=definition.data_type, rules=dict(definition.validation_rules or {})
        )
        if issues:
            raise StateConflictError(
                "The proposed value failed validation.",
                details={"issues": [{"code": i.code, "message": i.message} for i in issues]},
            )
        if legal_entity_id is None and definition.reusable_policy != (
            ReusablePolicy.ALL_ENTITIES_APPROVED.value
        ):
            raise StateConflictError(
                "A value must be scoped to a legal entity unless the definition is "
                "explicitly approved for all entities."
            )

        highest = (
            await self.session.scalar(
                select(func.max(InformationValue.value_version)).where(
                    InformationValue.information_definition_id == information_definition_id,
                    InformationValue.legal_entity_id == legal_entity_id,
                    InformationValue.jurisdiction_id == jurisdiction_id,
                )
            )
            or 0
        )

        record = InformationValue(
            id=uuid.uuid4(),
            information_definition_id=information_definition_id,
            legal_entity_id=legal_entity_id,
            jurisdiction_id=jurisdiction_id,
            license_id=license_id,
            vendor_organization_id=vendor_organization_id,
            compliance_case_id=compliance_case_id,
            value_version=highest + 1,
            status=InformationValueStatus.DRAFT.value,
            valid_from=valid_from,
            valid_to=valid_to,
            owner_actor=owner_actor or actor.actor_id,
            source_document_id=source_document_id,
            source_reference=source_reference,
            created_by_actor=actor.actor_id,
            value_fingerprint="",
        )

        if requires_encryption(definition.sensitivity):
            cipher = self._get_cipher()
            record.value_encrypted = cipher.encrypt(
                value, entity_type=_ENTITY_TYPE, entity_id=str(record.id)
            )
            record.value_fingerprint = cipher.fingerprint(value)
        else:
            # INTERNAL data is non-secret by policy, so it does not require key
            # material merely to use the registry. Sensitive tiers never enter
            # this branch.
            record.value_plain = {"value": value}
            record.value_fingerprint = content_sha256(value)
        record.display_value_redacted = (
            str(value)[:200]
            if definition.sensitivity == Sensitivity.INTERNAL.value
            else redact(value, keep_last=definition.display_keep_last)
        )

        self.session.add(record)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="information_value",
            entity_id=record.id,
            action="information_value_proposed",
            after={
                "information_key": definition.information_key,
                "version": record.value_version,
                "sensitivity": definition.sensitivity,
            },
        )
        if commit:
            await self.session.commit()
        return record

    async def submit_for_approval(
        self, value_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True
    ) -> InformationValue:
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        if record.status != InformationValueStatus.DRAFT.value:
            raise StateConflictError("Only a DRAFT value can be submitted for approval.")
        record.status = InformationValueStatus.PENDING_APPROVAL.value
        if commit:
            await self.session.commit()
        return record

    async def approve_value(
        self,
        value_id: uuid.UUID,
        *,
        actor: CurrentActor,
        cross_entity_approved: bool = False,
        commit: bool = True,
    ) -> InformationValue:
        """Approve a value, superseding the previous approved version in scope."""
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        if record.status not in (
            InformationValueStatus.DRAFT.value,
            InformationValueStatus.PENDING_APPROVAL.value,
        ):
            raise StateConflictError(f"A value in {record.status} cannot be approved.")
        definition = await self.session.get(InformationDefinition, record.information_definition_id)
        if definition is None:
            raise NotFoundError("Information definition not found.")
        if not record.owner_actor:
            raise StateConflictError("An approved value must have an accountable owner.")

        if cross_entity_approved:
            if not has_role(actor.roles, Role.MANAGER):
                raise SensitiveAccessDeniedError(
                    "Cross-entity reuse approval requires the Manager role."
                )
            if definition.reusable_policy != ReusablePolicy.ALL_ENTITIES_APPROVED.value:
                raise StateConflictError(
                    "This definition is not marked ALL_ENTITIES_APPROVED, so cross-entity "
                    "reuse cannot be granted."
                )
            record.cross_entity_approved_by_actor = actor.actor_id
            record.cross_entity_approved_at = utcnow()

        # Supersede the current approved value in the same scope first: the
        # partial unique index permits exactly one APPROVED row per scope.
        current = await self.session.scalar(
            select(InformationValue).where(
                InformationValue.id != record.id,
                InformationValue.information_definition_id == record.information_definition_id,
                InformationValue.legal_entity_id == record.legal_entity_id,
                InformationValue.jurisdiction_id == record.jurisdiction_id,
                InformationValue.status == InformationValueStatus.APPROVED.value,
            )
        )
        if current is not None:
            current.status = InformationValueStatus.SUPERSEDED.value
            current.superseded_by_value_id = record.id
            await self.session.flush()

        record.status = InformationValueStatus.APPROVED.value
        record.approved_by_actor = actor.actor_id
        record.approved_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="information_value",
            entity_id=record.id,
            action="information_value_approved",
            after={
                "version": record.value_version,
                "superseded_version": current.value_version if current else None,
                "cross_entity": bool(cross_entity_approved),
            },
        )
        if commit:
            await self.session.commit()
        return record

    async def reject_value(
        self, value_id: uuid.UUID, *, actor: CurrentActor, reason: str, commit: bool = True
    ) -> InformationValue:
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        record.status = InformationValueStatus.REJECTED.value
        record.rejection_reason = reason[:1000]
        if commit:
            await self.session.commit()
        return record

    async def supersede_value(
        self, value_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True
    ) -> InformationValue:
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        record.status = InformationValueStatus.SUPERSEDED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="information_value",
            entity_id=record.id,
            action="information_value_superseded",
        )
        if commit:
            await self.session.commit()
        return record

    # --------------------------------------------------------------------- lookup
    async def resolve_for_use(
        self,
        *,
        information_key: str,
        context: UsageContext,
        allow_stale: bool = False,
    ) -> dict[str, Any]:
        """Find a usable approved value for a key in one context.

        Returns a structured decision rather than raising, so a form preparer can
        record ``NEEDS_INFORMATION`` and raise a request instead of failing.
        """
        definition = await self.session.scalar(
            select(InformationDefinition).where(
                InformationDefinition.information_key == information_key
            )
        )
        if definition is None:
            return {"found": False, "reason": "DEFINITION_NOT_FOUND", "definition": None}

        candidates = list(
            await self.session.scalars(
                select(InformationValue)
                .where(
                    InformationValue.information_definition_id == definition.id,
                    InformationValue.status == InformationValueStatus.APPROVED.value,
                )
                .order_by(InformationValue.value_version.desc())
            )
        )
        rejections: list[str] = []
        for candidate in candidates:
            decision = evaluate_reuse(
                status=candidate.status,
                reusable_policy=definition.reusable_policy,
                sensitivity=definition.sensitivity,
                scope=ValueScope(
                    legal_entity_id=candidate.legal_entity_id,
                    jurisdiction_id=candidate.jurisdiction_id,
                    license_id=candidate.license_id,
                    vendor_organization_id=candidate.vendor_organization_id,
                    compliance_case_id=candidate.compliance_case_id,
                ),
                context=context,
                owner_actor=candidate.owner_actor,
                approved_at=candidate.approved_at,
                valid_from=candidate.valid_from,
                valid_to=candidate.valid_to,
                freshness_days=definition.freshness_days,
                cross_entity_approved=candidate.cross_entity_approved_by_actor is not None,
                allow_stale=allow_stale,
            )
            if decision.usable:
                return {
                    "found": True,
                    "value_id": candidate.id,
                    "value_version": candidate.value_version,
                    "display_value": candidate.display_value_redacted,
                    "definition": definition,
                    "record": candidate,
                    "freshness": decision.freshness,
                }
            rejections.extend(decision.reasons)

        return {
            "found": False,
            "reason": rejections[0] if rejections else "NO_APPROVED_VALUE",
            "all_reasons": sorted(set(rejections)),
            "definition": definition,
        }

    async def reveal_value(
        self,
        value_id: uuid.UUID,
        *,
        actor: CurrentActor,
        purpose: str = UsagePurpose.MANUAL_LOOKUP.value,
        commit: bool = True,
    ) -> Any:
        """Decrypt a value for an authorised human. Always audited.

        Restricted and above require Manager or the recorded owner; nothing here is
        ever exposed to an AI model.
        """
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        definition = await self.session.get(InformationDefinition, record.information_definition_id)
        if definition is None:
            raise NotFoundError("Information definition not found.")

        if requires_encryption(definition.sensitivity):
            permitted = has_role(actor.roles, Role.MANAGER) or (
                record.owner_actor == actor.actor_id
            )
            if not permitted:
                raise SensitiveAccessDeniedError(
                    "Revealing a restricted value requires the Manager role or ownership."
                )
        if (
            definition.sensitivity == Sensitivity.HIGHLY_RESTRICTED.value
            and not self.settings.information_highly_restricted_enabled
        ):
            raise SensitiveAccessDeniedError(
                "Highly restricted values are disabled in this environment."
            )

        if record.value_encrypted:
            plaintext = self._get_cipher().decrypt_json(
                record.value_encrypted,
                entity_type=_ENTITY_TYPE,
                entity_id=str(record.id),
            )
        elif not requires_encryption(definition.sensitivity) and record.value_plain:
            plaintext = record.value_plain
        else:
            raise StateConflictError("This value has no protected stored representation.")
        # The audit records the reveal; the value itself is never logged.
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="information_value",
            entity_id=record.id,
            action="information_value_revealed",
            metadata={"purpose": purpose, "sensitivity": definition.sensitivity},
        )
        if commit:
            await self.session.commit()
        return plaintext.get("value") if isinstance(plaintext, dict) else plaintext

    async def record_usage(
        self,
        value_id: uuid.UUID,
        *,
        purpose: str,
        actor: CurrentActor | None = None,
        compliance_case_id: uuid.UUID | None = None,
        form_instance_id: uuid.UUID | None = None,
        packet_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> InformationValueUsage:
        record = await self.session.get(InformationValue, value_id)
        if record is None:
            raise NotFoundError("Information value not found.")
        usage = InformationValueUsage(
            information_value_id=value_id,
            compliance_case_id=compliance_case_id,
            form_instance_id=form_instance_id,
            packet_id=packet_id,
            used_by_actor=actor.actor_id if actor else "licensing-worker",
            purpose=purpose,
            used_value_version=record.value_version,
            used_at=utcnow(),
        )
        self.session.add(usage)
        record.last_used_at = utcnow()
        if commit:
            await self.session.commit()
        return usage

    async def expire_stale_values(self, *, commit: bool = True) -> dict[str, int]:
        """Mark past-validity approved values EXPIRED so they stop autofilling."""
        today = utcnow().date()
        expired = list(
            await self.session.scalars(
                select(InformationValue).where(
                    InformationValue.status == InformationValueStatus.APPROVED.value,
                    InformationValue.valid_to.is_not(None),
                    InformationValue.valid_to < today,
                )
            )
        )
        for record in expired:
            record.status = InformationValueStatus.EXPIRED.value

        stale = 0
        approved = list(
            await self.session.scalars(
                select(InformationValue, InformationDefinition)
                .join(
                    InformationDefinition,
                    InformationDefinition.id == InformationValue.information_definition_id,
                )
                .where(InformationValue.status == InformationValueStatus.APPROVED.value)
            )
        )
        for record in approved:
            definition = await self.session.get(
                InformationDefinition, record.information_definition_id
            )
            if definition is None:
                continue
            freshness = assess_freshness(
                approved_at=record.approved_at,
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                freshness_days=definition.freshness_days,
                today=today,
            )
            if freshness in (ValueFreshness.STALE.value, ValueFreshness.EXPIRED.value):
                stale += 1
        INFORMATION_VALUES_STALE.set(stale)
        if commit:
            await self.session.commit()
        return {"expired": len(expired), "stale": stale}
