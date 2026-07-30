"""Legal entities, operating profiles, and the central licence inventory."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import LICENSING_ACTIVE_LICENSES, LICENSING_INVENTORY_TOTAL
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import (
    LIVE_LICENSE_STATUSES,
    TERMINAL_LICENSE_STATUSES,
    EntityStatus,
    FilingChannel,
    LicenseEventSourceType,
    LicenseStatus,
    ProfileStatus,
    SourceConfidence,
)
from app.models import (
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicenseStatusEvent,
    LicenseType,
    OperatingProfile,
)
from app.models.mixins import utcnow

_KEY_SAFE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, fallback: str = "item") -> str:
    cleaned = _KEY_SAFE.sub("-", (value or "").lower()).strip("-")
    return (cleaned or fallback)[:80]


class LicenseInventoryService:
    """Owns entity, profile, and licence-record mutations.

    Every status change appends a :class:`LicenseStatusEvent`; history is never
    edited in place, so the inventory can always explain how it reached a state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ entities
    async def create_legal_entity(
        self, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> LegalEntity:
        entity_key = fields.get("entity_key") or slugify(fields["legal_name"], fallback="entity")
        existing = await self.session.scalar(
            select(LegalEntity).where(LegalEntity.entity_key == entity_key)
        )
        if existing:
            raise StateConflictError(f"Legal entity key {entity_key!r} already exists.")
        entity = LegalEntity(
            entity_key=entity_key,
            legal_name=fields["legal_name"],
            display_name=fields.get("display_name"),
            entity_type=fields["entity_type"],
            formation_jurisdiction=fields.get("formation_jurisdiction"),
            formation_date=fields.get("formation_date"),
            tax_identifier_reference=fields.get("tax_identifier_reference"),
            nmls_id=fields.get("nmls_id"),
            primary_business_address=fields.get("primary_business_address"),
            mailing_address=fields.get("mailing_address"),
            status=fields.get("status") or EntityStatus.ACTIVE.value,
            is_in_scope=fields.get("is_in_scope", True),
            out_of_scope_reason=fields.get("out_of_scope_reason"),
        )
        self.session.add(entity)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="legal_entity",
            entity_id=entity.id,
            action="legal_entity_created",
            after={"entity_key": entity.entity_key, "status": entity.status},
        )
        if commit:
            await self.session.commit()
        return entity

    async def update_legal_entity(
        self, entity_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> LegalEntity:
        entity = await self.session.get(LegalEntity, entity_id)
        if entity is None:
            raise NotFoundError("Legal entity not found.")
        before = {"status": entity.status, "is_in_scope": entity.is_in_scope}
        for key, value in fields.items():
            if value is not None and hasattr(entity, key) and key not in ("id", "entity_key"):
                setattr(entity, key, value)
        if not entity.is_in_scope and not entity.out_of_scope_reason:
            raise StateConflictError("An out-of-scope entity requires a reason.")
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="legal_entity",
            entity_id=entity.id,
            action="legal_entity_updated",
            before=before,
            after={"status": entity.status, "is_in_scope": entity.is_in_scope},
        )
        if commit:
            await self.session.commit()
        return entity

    # ------------------------------------------------------------------ profiles
    async def create_operating_profile(
        self,
        entity_id: uuid.UUID,
        *,
        name: str,
        facts: dict[str, Any],
        actor: CurrentActor,
        effective_from: date | None = None,
        commit: bool = True,
    ) -> OperatingProfile:
        entity = await self.session.get(LegalEntity, entity_id)
        if entity is None:
            raise NotFoundError("Legal entity not found.")
        highest = await self.session.scalar(
            select(func.max(OperatingProfile.version)).where(
                OperatingProfile.legal_entity_id == entity_id, OperatingProfile.name == name
            )
        )
        profile = OperatingProfile(
            legal_entity_id=entity_id,
            name=name,
            version=(highest or 0) + 1,
            status=ProfileStatus.DRAFT.value,
            facts=facts,
            effective_from=effective_from,
        )
        self.session.add(profile)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="operating_profile",
            entity_id=profile.id,
            action="operating_profile_created",
            after={"version": profile.version, "name": name},
        )
        if commit:
            await self.session.commit()
        return profile

    async def approve_operating_profile(
        self, profile_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True
    ) -> OperatingProfile:
        """Activate a draft profile, retiring the previous active version."""
        profile = await self.session.get(OperatingProfile, profile_id)
        if profile is None:
            raise NotFoundError("Operating profile not found.")
        if profile.status != ProfileStatus.DRAFT.value:
            raise StateConflictError("Only a DRAFT profile version can be approved.")
        current = await self.session.scalar(
            select(OperatingProfile).where(
                OperatingProfile.legal_entity_id == profile.legal_entity_id,
                OperatingProfile.name == profile.name,
                OperatingProfile.status == ProfileStatus.ACTIVE.value,
            )
        )
        if current is not None:
            # Retire before activating: the partial unique index permits exactly
            # one ACTIVE version per (entity, profile name).
            current.status = ProfileStatus.RETIRED.value
            current.effective_to = utcnow().date()
            await self.session.flush()
        profile.status = ProfileStatus.ACTIVE.value
        profile.approved_by_actor = actor.actor_id
        profile.approved_at = utcnow()
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="operating_profile",
            entity_id=profile.id,
            action="operating_profile_approved",
            after={"version": profile.version},
            metadata={"retired_version": current.version if current else None},
        )
        if commit:
            await self.session.commit()
        return profile

    # ----------------------------------------------------------------- inventory
    async def create_license(
        self,
        *,
        actor: CurrentActor,
        legal_entity_id: uuid.UUID,
        jurisdiction_id: uuid.UUID,
        license_type_id: uuid.UUID,
        commit: bool = True,
        **fields: Any,
    ) -> LicenseInventory:
        entity = await self.session.get(LegalEntity, legal_entity_id)
        jurisdiction = await self.session.get(Jurisdiction, jurisdiction_id)
        license_type = await self.session.get(LicenseType, license_type_id)
        if entity is None or jurisdiction is None or license_type is None:
            raise NotFoundError("Entity, jurisdiction, or licence type not found.")

        status = fields.get("current_status") or LicenseStatus.NOT_STARTED.value
        additional = bool(fields.get("represents_additional_authority", False))
        if status in LIVE_LICENSE_STATUSES and not additional:
            clash = await self.session.scalar(
                select(LicenseInventory).where(
                    LicenseInventory.legal_entity_id == legal_entity_id,
                    LicenseInventory.jurisdiction_id == jurisdiction_id,
                    LicenseInventory.license_type_id == license_type_id,
                    LicenseInventory.represents_additional_authority.is_(False),
                    LicenseInventory.current_status.in_(LIVE_LICENSE_STATUSES),
                )
            )
            if clash is not None:
                raise StateConflictError(
                    "A live licence already exists for this entity, jurisdiction, and "
                    "type. Mark the new record as an additional authority if the entity "
                    "genuinely holds more than one.",
                    details={"existing_license_key": clash.license_key},
                )

        license_key = (
            fields.get("license_key")
            or "-".join(
                [
                    entity.entity_key,
                    jurisdiction.jurisdiction_key,
                    license_type.license_type_key,
                    slugify(str(fields.get("license_number") or "primary")),
                ]
            )[:120]
        )
        record = LicenseInventory(
            license_key=license_key,
            legal_entity_id=legal_entity_id,
            jurisdiction_id=jurisdiction_id,
            license_type_id=license_type_id,
            regulator_organization_id=fields.get("regulator_organization_id"),
            vendor_organization_id=fields.get("vendor_organization_id"),
            license_number=fields.get("license_number"),
            nmls_license_id=fields.get("nmls_license_id"),
            filing_channel=fields.get("filing_channel") or FilingChannel.UNKNOWN.value,
            current_status=status,
            represents_additional_authority=additional,
            authority_label=fields.get("authority_label"),
            issue_date=fields.get("issue_date"),
            effective_date=fields.get("effective_date"),
            expiration_date=fields.get("expiration_date"),
            renewal_due_date=fields.get("renewal_due_date"),
            internal_start_date=fields.get("internal_start_date"),
            next_review_date=fields.get("next_review_date"),
            responsible_owner=fields.get("responsible_owner"),
            source_document_id=fields.get("source_document_id"),
            notes=fields.get("notes"),
            source_confidence=fields.get("source_confidence")
            or SourceConfidence.MANUAL_ENTRY.value,
            last_verified_at=fields.get("last_verified_at"),
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            LicenseStatusEvent(
                license_id=record.id,
                from_status=None,
                to_status=record.current_status,
                effective_at=utcnow(),
                actor_id=actor.actor_id,
                source_type=fields.get("event_source_type")
                or LicenseEventSourceType.MANUAL_UPDATE.value,
                source_reference=fields.get("event_source_reference"),
                note="Licence record created.",
                occurred_at=utcnow(),
            )
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="license_inventory",
            entity_id=record.id,
            action="license_created",
            after={"status": record.current_status, "filing_channel": record.filing_channel},
        )
        if commit:
            await self.session.commit()
        return record

    async def transition_status(
        self,
        license_id: uuid.UUID,
        *,
        to_status: str,
        actor: CurrentActor,
        source_type: str | None = None,
        source_reference: str | None = None,
        note: str | None = None,
        effective_at: Any = None,
        commit: bool = True,
    ) -> LicenseInventory:
        """Move a licence to a new status and append immutable history."""
        record = await self.session.get(LicenseInventory, license_id)
        if record is None:
            raise NotFoundError("Licence not found.")
        if to_status not in {member.value for member in LicenseStatus}:
            raise StateConflictError(f"Unknown licence status {to_status!r}.")
        if record.current_status in TERMINAL_LICENSE_STATUSES and to_status not in (
            LicenseStatus.REINSTATING.value,
            LicenseStatus.APPLICATION_IN_PROGRESS.value,
        ):
            raise StateConflictError(
                f"{record.current_status} is terminal; only reinstatement or a new "
                "application may follow."
            )
        # Re-entering a live status must not create a second live authority.
        if (
            to_status in LIVE_LICENSE_STATUSES
            and record.current_status not in LIVE_LICENSE_STATUSES
            and not record.represents_additional_authority
        ):
            clash = await self.session.scalar(
                select(LicenseInventory).where(
                    LicenseInventory.id != record.id,
                    LicenseInventory.legal_entity_id == record.legal_entity_id,
                    LicenseInventory.jurisdiction_id == record.jurisdiction_id,
                    LicenseInventory.license_type_id == record.license_type_id,
                    LicenseInventory.represents_additional_authority.is_(False),
                    LicenseInventory.current_status.in_(LIVE_LICENSE_STATUSES),
                )
            )
            if clash is not None:
                raise StateConflictError(
                    "Another live licence already occupies this entity/jurisdiction/type."
                )

        previous = record.current_status
        record.current_status = to_status
        if to_status == LicenseStatus.SURRENDERED.value and not record.surrender_date:
            record.surrender_date = utcnow().date()
        self.session.add(
            LicenseStatusEvent(
                license_id=record.id,
                from_status=previous,
                to_status=to_status,
                effective_at=effective_at or utcnow(),
                actor_id=actor.actor_id,
                source_type=source_type or LicenseEventSourceType.MANUAL_UPDATE.value,
                source_reference=source_reference,
                note=note,
                occurred_at=utcnow(),
            )
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="license_inventory",
            entity_id=record.id,
            action="license_status_changed",
            before={"status": previous},
            after={"status": to_status},
        )
        if commit:
            await self.session.commit()
        return record

    async def update_license(
        self, license_id: uuid.UUID, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> LicenseInventory:
        record = await self.session.get(LicenseInventory, license_id)
        if record is None:
            raise NotFoundError("Licence not found.")
        protected = {"id", "license_key", "current_status", "legal_entity_id"}
        before = {"expiration_date": str(record.expiration_date)}
        for key, value in fields.items():
            if value is not None and hasattr(record, key) and key not in protected:
                setattr(record, key, value)
        if (
            record.issue_date
            and record.expiration_date
            and record.expiration_date < record.issue_date
        ):
            raise StateConflictError("Expiration cannot precede the issue date.")
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="license_inventory",
            entity_id=record.id,
            action="license_updated",
            before=before,
            after={"expiration_date": str(record.expiration_date)},
        )
        if commit:
            await self.session.commit()
        return record

    async def record_renewed_evidence(
        self,
        license_id: uuid.UUID,
        *,
        actor: CurrentActor,
        new_expiration_date: date,
        evidence_document_id: uuid.UUID | None = None,
        new_issue_date: date | None = None,
        license_number: str | None = None,
        commit: bool = True,
    ) -> LicenseInventory:
        """Apply renewed evidence and return the licence to ACTIVE."""
        record = await self.session.get(LicenseInventory, license_id)
        if record is None:
            raise NotFoundError("Licence not found.")
        before = {
            "expiration_date": str(record.expiration_date),
            "status": record.current_status,
        }
        record.expiration_date = new_expiration_date
        record.renewal_due_date = new_expiration_date
        if new_issue_date:
            record.issue_date = new_issue_date
        if license_number:
            record.license_number = license_number
        if evidence_document_id:
            record.source_document_id = evidence_document_id
        record.source_confidence = SourceConfidence.VERIFIED_DOCUMENT.value
        record.last_verified_at = utcnow()
        previous = record.current_status
        record.current_status = LicenseStatus.ACTIVE.value
        self.session.add(
            LicenseStatusEvent(
                license_id=record.id,
                from_status=previous,
                to_status=LicenseStatus.ACTIVE.value,
                effective_at=utcnow(),
                actor_id=actor.actor_id,
                source_type=LicenseEventSourceType.CASE_COMPLETION.value,
                source_reference=str(evidence_document_id) if evidence_document_id else None,
                note="Renewed evidence recorded.",
                occurred_at=utcnow(),
            )
        )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="license_inventory",
            entity_id=record.id,
            action="license_renewed",
            before=before,
            after={
                "expiration_date": str(record.expiration_date),
                "status": record.current_status,
            },
        )
        if commit:
            await self.session.commit()
        return record

    async def refresh_metrics(self) -> None:
        total = await self.session.scalar(select(func.count()).select_from(LicenseInventory)) or 0
        active = (
            await self.session.scalar(
                select(func.count())
                .select_from(LicenseInventory)
                .where(LicenseInventory.current_status == LicenseStatus.ACTIVE.value)
            )
            or 0
        )
        LICENSING_INVENTORY_TOTAL.set(total)
        LICENSING_ACTIVE_LICENSES.set(active)
