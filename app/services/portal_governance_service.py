"""Portal inventory, legal/security review, adapters, and user authorization."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.exceptions import NotFoundError, StateConflictError
from app.licensing.audit import add_licensing_audit
from app.models import (
    Jurisdiction,
    LegalEntity,
    Organization,
    PortalAdapterVersion,
    PortalDefinition,
    PortalFieldMapping,
    PortalReviewVersion,
    PortalUserAuthorization,
    UserPrincipal,
)
from app.models.mixins import utcnow
from app.portals.enums import (
    AdapterStatus,
    AuthorizationStatus,
    AutomationLevel,
    CredentialModel,
    PortalApprovalStatus,
    PortalFieldSourceType,
    PortalReviewStatus,
    PortalType,
)
from app.portals.policies import ABSOLUTELY_PROHIBITED_ACTIONS, portal_can_activate
from app.portals.registry import build_adapter
from app.portals.validation import validate_locator_contract, validate_portal_url

_SECRET_PATTERN = re.compile(
    r"(password|passwd|secret|otp|mfa|cookie|bearer|access.?token)\s*[:=]",
    re.IGNORECASE,
)
_HUMAN_ONLY_SOURCE_TYPES = {
    PortalFieldSourceType.ATTESTATION.value,
    PortalFieldSourceType.SIGNATURE.value,
    PortalFieldSourceType.PAYMENT.value,
    PortalFieldSourceType.MANUAL_OPERATOR_INPUT.value,
}


class PortalGovernanceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def create_portal(
        self, *, actor: CurrentActor, fields: dict[str, Any]
    ) -> PortalDefinition:
        base_url, hostname = validate_portal_url(
            fields["base_url"], self.settings.portal_allowed_hosts
        )
        self._validate_portal_enums(fields)
        if await self.session.scalar(
            select(PortalDefinition.id).where(PortalDefinition.portal_key == fields["portal_key"])
        ):
            raise StateConflictError("Portal key already exists.")
        if fields.get("owner_organization_id") and not await self.session.get(
            Organization, fields["owner_organization_id"]
        ):
            raise NotFoundError("Owner organization not found.")
        if fields.get("jurisdiction_id") and not await self.session.get(
            Jurisdiction, fields["jurisdiction_id"]
        ):
            raise NotFoundError("Jurisdiction not found.")
        portal = PortalDefinition(
            **fields,
            base_url=base_url,
            hostname=hostname,
            status=PortalApprovalStatus.DISCOVERED.value,
            final_submit_human_only=True,
            payment_human_only=True,
            attestation_human_only=True,
            signature_human_only=True,
        )
        self.session.add(portal)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_definition",
            entity_id=portal.id,
            action="portal_registered",
            after={
                "portal_type": portal.portal_type,
                "automation_level": portal.approved_automation_level,
                "status": portal.status,
            },
        )
        await self.session.commit()
        return portal

    async def update_portal(
        self,
        portal_id: uuid.UUID,
        *,
        actor: CurrentActor,
        changes: dict[str, Any],
    ) -> PortalDefinition:
        portal = await self._portal(portal_id)
        if "approved_automation_level" in changes and changes["approved_automation_level"] not in {
            item.value for item in AutomationLevel
        }:
            raise StateConflictError("Unknown automation level.")
        if "status" in changes and changes["status"] not in {
            item.value for item in PortalApprovalStatus
        }:
            raise StateConflictError("Unknown portal status.")
        if changes.get("status") in {
            PortalApprovalStatus.APPROVED_ASSISTED.value,
            PortalApprovalStatus.APPROVED_API.value,
        }:
            review = await self.active_review(portal.id)
            if review is None:
                raise StateConflictError("Portal cannot be enabled without an active review.")
        before = {field: getattr(portal, field) for field in changes if hasattr(portal, field)}
        for field, value in changes.items():
            setattr(portal, field, value)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_definition",
            entity_id=portal.id,
            action="portal_updated",
            before=before,
            after={field: getattr(portal, field) for field in before},
        )
        await self.session.commit()
        return portal

    async def create_review(
        self,
        portal_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> PortalReviewVersion:
        portal = await self._portal(portal_id)
        next_version = (
            await self.session.scalar(
                select(func.max(PortalReviewVersion.version)).where(
                    PortalReviewVersion.portal_definition_id == portal.id
                )
            )
            or 0
        ) + 1
        valid_to = fields.get("valid_to") or (
            utcnow() + timedelta(days=self.settings.portal_terms_review_max_age_days)
        )
        if fields.get("valid_from") and fields["valid_from"] >= valid_to:
            raise StateConflictError("Review valid_to must follow valid_from.")
        review_fields = dict(fields)
        review_fields["valid_to"] = valid_to
        review_fields["reviewed_by_compliance"] = None
        review_fields["reviewed_by_security"] = None
        review = PortalReviewVersion(
            portal_definition_id=portal.id,
            version=next_version,
            status=PortalReviewStatus.DRAFT.value,
            **review_fields,
        )
        self.session.add(review)
        portal.status = PortalApprovalStatus.REVIEW_PENDING.value
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_review_version",
            entity_id=review.id,
            action="portal_review_created",
            after={"version": review.version, "status": review.status},
        )
        await self.session.commit()
        return review

    async def record_review_signoff(
        self,
        review_id: uuid.UUID,
        *,
        actor: CurrentActor,
        review_domain: str,
    ) -> PortalReviewVersion:
        review = await self.session.get(PortalReviewVersion, review_id)
        if review is None:
            raise NotFoundError("Portal review not found.")
        if review.status != PortalReviewStatus.DRAFT.value:
            raise StateConflictError("Only a draft portal review can receive sign-off.")
        if review_domain == "compliance":
            review.reviewed_by_compliance = actor.actor_id
        elif review_domain == "security":
            review.reviewed_by_security = actor.actor_id
        else:
            raise StateConflictError("Unknown portal review sign-off domain.")
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_review_version",
            entity_id=review.id,
            action=f"portal_review_{review_domain}_signed_off",
        )
        await self.session.commit()
        return review

    async def approve_review(
        self, review_id: uuid.UUID, *, actor: CurrentActor
    ) -> PortalReviewVersion:
        review = await self.session.get(PortalReviewVersion, review_id)
        if review is None:
            raise NotFoundError("Portal review not found.")
        if review.status != PortalReviewStatus.DRAFT.value:
            raise StateConflictError("Only a draft review can be approved.")
        portal = await self._portal(review.portal_definition_id)
        if portal.terms_review_required and not (review.terms_reference and review.terms_sha256):
            raise StateConflictError("Terms reference and hash are required.")
        if not review.reviewed_by_compliance or not review.reviewed_by_security:
            raise StateConflictError("Compliance and security reviewers are required.")
        if review.security_findings:
            unresolved = [
                finding
                for finding in review.security_findings
                if str(finding.get("status", "OPEN")).upper() not in {"RESOLVED", "ACCEPTED"}
            ]
            if unresolved:
                raise StateConflictError("Unresolved security findings block approval.")
        prohibited = {
            action
            for action in ABSOLUTELY_PROHIBITED_ACTIONS
            if not bool(review.prohibited_actions.get(action))
        }
        if prohibited:
            raise StateConflictError(
                "Review must explicitly prohibit: " + ", ".join(sorted(prohibited))
            )
        contradictory = {
            action
            for action in ABSOLUTELY_PROHIBITED_ACTIONS
            if bool(review.allowed_actions.get(action))
        }
        if contradictory:
            raise StateConflictError(
                "Human-only actions cannot also be allowed: " + ", ".join(sorted(contradictory))
            )
        current = await self.active_review(portal.id)
        if current and current.id != review.id:
            current.status = PortalReviewStatus.SUPERSEDED.value
        review.status = PortalReviewStatus.APPROVED.value
        review.approved_by_actor = actor.actor_id
        review.valid_from = review.valid_from or utcnow()
        portal.terms_review_expires_at = review.valid_to
        portal.last_verified_at = utcnow()
        if portal.approved_automation_level == AutomationLevel.PREPARE_ONLY.value:
            portal.status = PortalApprovalStatus.APPROVED_PREPARE_ONLY.value
        elif portal.approved_automation_level == AutomationLevel.API_ASSISTED.value:
            portal.status = PortalApprovalStatus.APPROVED_API.value
        else:
            portal.status = PortalApprovalStatus.APPROVED_ASSISTED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_review_version",
            entity_id=review.id,
            action="portal_review_approved",
            after={"version": review.version, "portal_status": portal.status},
        )
        await self.session.commit()
        return review

    async def suspend_review(
        self, review_id: uuid.UUID, *, actor: CurrentActor, reason: str
    ) -> PortalReviewVersion:
        review = await self.session.get(PortalReviewVersion, review_id)
        if review is None:
            raise NotFoundError("Portal review not found.")
        if review.status != PortalReviewStatus.APPROVED.value:
            raise StateConflictError("Only an approved review can be suspended.")
        review.status = PortalReviewStatus.SUSPENDED.value
        portal = await self._portal(review.portal_definition_id)
        portal.status = PortalApprovalStatus.TEMPORARILY_SUSPENDED.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_review_version",
            entity_id=review.id,
            action="portal_review_suspended",
            metadata={"reason": reason[:500]},
        )
        await self.session.commit()
        return review

    async def create_adapter(
        self,
        portal_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> PortalAdapterVersion:
        await self._portal(portal_id)
        if fields["adapter_key"] == "official-api-assisted":
            self._validate_official_api_routes(fields["supported_routes"])
        else:
            validate_locator_contract(fields["locator_contract"])
            build_adapter(
                fields["adapter_key"],
                locator_contract=fields["locator_contract"],
                contract_version="draft",
            )
        next_version = (
            await self.session.scalar(
                select(func.max(PortalAdapterVersion.version)).where(
                    PortalAdapterVersion.portal_definition_id == portal_id,
                    PortalAdapterVersion.adapter_key == fields["adapter_key"],
                )
            )
            or 0
        ) + 1
        adapter = PortalAdapterVersion(
            portal_definition_id=portal_id,
            version=next_version,
            status=AdapterStatus.DRAFT.value,
            **fields,
        )
        self.session.add(adapter)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_adapter_version",
            entity_id=adapter.id,
            action="portal_adapter_created",
            after={"adapter_key": adapter.adapter_key, "version": adapter.version},
        )
        await self.session.commit()
        return adapter

    async def activate_adapter(
        self, adapter_id: uuid.UUID, *, actor: CurrentActor
    ) -> PortalAdapterVersion:
        adapter = await self.session.get(PortalAdapterVersion, adapter_id)
        if adapter is None:
            raise NotFoundError("Portal adapter not found.")
        portal = await self._portal(adapter.portal_definition_id)
        if not portal_can_activate(portal.status) or await self.active_review(portal.id) is None:
            raise StateConflictError("Current portal approval is required before activation.")
        if adapter.adapter_key == "official-api-assisted":
            self._validate_official_api_routes(adapter.supported_routes)
        else:
            validate_locator_contract(adapter.locator_contract)
            build_adapter(
                adapter.adapter_key,
                locator_contract=adapter.locator_contract,
                contract_version=str(adapter.version),
            )
        current = await self.session.scalar(
            select(PortalAdapterVersion).where(
                PortalAdapterVersion.portal_definition_id == portal.id,
                PortalAdapterVersion.adapter_key == adapter.adapter_key,
                PortalAdapterVersion.status == AdapterStatus.ACTIVE.value,
            )
        )
        if current and current.id != adapter.id:
            current.status = AdapterStatus.SUSPENDED.value
        adapter.status = AdapterStatus.ACTIVE.value
        adapter.approved_by_actor = actor.actor_id
        adapter.activated_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_adapter_version",
            entity_id=adapter.id,
            action="portal_adapter_activated",
            after={"adapter_key": adapter.adapter_key, "version": adapter.version},
        )
        await self.session.commit()
        return adapter

    async def add_field_mapping(
        self,
        adapter_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> PortalFieldMapping:
        adapter = await self.session.get(PortalAdapterVersion, adapter_id)
        if adapter is None:
            raise NotFoundError("Portal adapter not found.")
        if adapter.status == AdapterStatus.ACTIVE.value:
            raise StateConflictError("Active adapter mappings are immutable; create a new version.")
        source_type = fields["source_type"]
        if source_type not in {item.value for item in PortalFieldSourceType}:
            raise StateConflictError("Unknown portal field source type.")
        if source_type in _HUMAN_ONLY_SOURCE_TYPES:
            fields["human_only"] = True
        mapping = PortalFieldMapping(portal_adapter_version_id=adapter.id, **fields)
        self.session.add(mapping)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_field_mapping",
            entity_id=mapping.id,
            action="portal_field_mapping_created",
            after={
                "field_key": mapping.portal_field_key,
                "source_type": mapping.source_type,
                "human_only": mapping.human_only,
            },
        )
        await self.session.commit()
        return mapping

    async def upsert_authorization(
        self,
        portal_id: uuid.UUID,
        *,
        actor: CurrentActor,
        fields: dict[str, Any],
    ) -> PortalUserAuthorization:
        await self._portal(portal_id)
        if await self.session.get(UserPrincipal, fields["user_principal_id"]) is None:
            raise NotFoundError("User principal not found.")
        if fields["authorization_status"] not in {item.value for item in AuthorizationStatus}:
            raise StateConflictError("Unknown portal authorization status.")
        external_reference = fields.get("external_account_reference")
        if external_reference and _SECRET_PATTERN.search(external_reference):
            raise StateConflictError("External account reference appears to contain a secret.")
        for entity_id in fields.get("authorized_entity_ids", []):
            if await self.session.get(LegalEntity, entity_id) is None:
                raise NotFoundError("Authorized legal entity not found.")
        authorization = await self.session.scalar(
            select(PortalUserAuthorization).where(
                PortalUserAuthorization.portal_definition_id == portal_id,
                PortalUserAuthorization.user_principal_id == fields["user_principal_id"],
            )
        )
        action = "portal_user_authorization_updated"
        if authorization is None:
            authorization = PortalUserAuthorization(portal_definition_id=portal_id, **fields)
            self.session.add(authorization)
            action = "portal_user_authorization_created"
        else:
            for field, value in fields.items():
                setattr(authorization, field, value)
        authorization.authorized_at = (
            utcnow()
            if authorization.authorization_status == AuthorizationStatus.ACTIVE.value
            else authorization.authorized_at
        )
        authorization.last_verified_at = utcnow()
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="portal_user_authorization",
            entity_id=authorization.id,
            action=action,
            after={"status": authorization.authorization_status},
        )
        await self.session.commit()
        return authorization

    async def active_review(self, portal_id: uuid.UUID) -> PortalReviewVersion | None:
        review: PortalReviewVersion | None = await self.session.scalar(
            select(PortalReviewVersion).where(
                PortalReviewVersion.portal_definition_id == portal_id,
                PortalReviewVersion.status == PortalReviewStatus.APPROVED.value,
            )
        )
        return review

    async def _portal(self, portal_id: uuid.UUID) -> PortalDefinition:
        portal = await self.session.get(PortalDefinition, portal_id)
        if portal is None:
            raise NotFoundError("Portal not found.")
        return portal

    @staticmethod
    def _validate_portal_enums(fields: dict[str, Any]) -> None:
        values = (
            ("portal_type", PortalType),
            ("approved_automation_level", AutomationLevel),
            ("credential_model", CredentialModel),
        )
        for field, enum_type in values:
            if fields[field] not in {item.value for item in enum_type}:
                raise StateConflictError(f"Unknown {field.replace('_', ' ')}.")

    @staticmethod
    def _validate_official_api_routes(routes: dict[str, Any]) -> None:
        if not routes:
            raise StateConflictError("Official API adapter requires reviewed route contracts.")
        serialized_keys = " ".join(str(key).casefold() for key in routes)
        if any(
            word in serialized_keys
            for word in ("submit", "attest", "payment", "signature", "terms", "captcha", "mfa")
        ):
            raise StateConflictError(
                "Official API route contracts cannot include human-only final actions."
            )
