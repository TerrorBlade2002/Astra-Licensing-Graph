"""Advisory requirement assessments: evaluate, review, override, counsel review.

Nothing in this service creates a licence record. An approved assessment may
*propose* an initial-licence obligation, which a human then accepts.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.crypto import content_sha256
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import (
    REQUIREMENT_ASSESSMENTS_TOTAL,
    REQUIREMENT_RESULTS_COUNSEL_REVIEW,
)
from app.licensing.audit import add_licensing_audit
from app.models import (
    AssessmentOverride,
    Jurisdiction,
    LegalEntity,
    OperatingProfile,
    RequirementAssessment,
    RequirementAssessmentResult,
    RequirementRule,
    RequirementRuleSet,
    RequirementRuleSource,
    RequirementSource,
    RequirementSourceSnapshot,
)
from app.models.mixins import utcnow
from app.requirements.evaluator import EvaluationSettings, evaluate_jurisdiction
from app.requirements.freshness import assess_source
from app.requirements.rules import Rule, SourceCitation
from app.requirements.taxonomy import (
    AssessmentStatus,
    AssessmentType,
    OverrideAuthority,
    RequirementOutcome,
    RuleSetStatus,
    SnapshotReviewStatus,
)


class RequirementAssessmentService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _load_active_rule_set(self, name: str | None = None) -> RequirementRuleSet:
        stmt = select(RequirementRuleSet).where(
            RequirementRuleSet.status == RuleSetStatus.ACTIVE.value
        )
        if name:
            stmt = stmt.where(RequirementRuleSet.name == name)
        rule_set = await self.session.scalar(stmt.order_by(RequirementRuleSet.version.desc()))
        if rule_set is None:
            raise StateConflictError(
                "No ACTIVE requirement rule set exists. Activate a reviewed rule set first."
            )
        return rule_set

    async def _load_rules(self, rule_set_id: uuid.UUID) -> list[Rule]:
        """Load rules with their approved citations attached."""
        rows = list(
            await self.session.scalars(
                select(RequirementRule).where(
                    RequirementRule.rule_set_id == rule_set_id,
                    RequirementRule.enabled.is_(True),
                )
            )
        )
        if not rows:
            return []
        links = (
            await self.session.execute(
                select(RequirementRuleSource, RequirementSourceSnapshot, RequirementSource)
                .join(
                    RequirementSourceSnapshot,
                    RequirementSourceSnapshot.id
                    == RequirementRuleSource.requirement_source_snapshot_id,
                )
                .join(
                    RequirementSource,
                    RequirementSource.id == RequirementSourceSnapshot.requirement_source_id,
                )
                .where(RequirementRuleSource.requirement_rule_id.in_([r.id for r in rows]))
            )
        ).all()

        citations: dict[uuid.UUID, list[SourceCitation]] = {}
        for link, snapshot, source in links:
            # Only an approved snapshot may back a live rule.
            if snapshot.review_status not in (
                SnapshotReviewStatus.APPROVED.value,
                SnapshotReviewStatus.SUPERSEDED.value,
            ):
                continue
            freshness = assess_source(
                source_type=source.source_type,
                authority_level=source.authority_level,
                last_verified_at=source.last_verified_at,
                override_days=source.freshness_days,
                default_days=self.settings.requirement_source_freshness_days,
            )
            citations.setdefault(link.requirement_rule_id, []).append(
                SourceCitation(
                    source_id=source.id,
                    snapshot_id=snapshot.id,
                    title=source.title,
                    authority_level=source.authority_level,
                    source_type=source.source_type,
                    official_url=source.official_url,
                    snapshot_version=snapshot.version,
                    last_verified_at=(
                        source.last_verified_at.date().isoformat()
                        if source.last_verified_at
                        else None
                    ),
                    effective_date=(
                        source.effective_date.isoformat() if source.effective_date else None
                    ),
                    citation_detail=link.citation_detail,
                    freshness_status=freshness.status,
                )
            )

        return [
            Rule(
                id=row.id,
                rule_key=row.rule_key,
                outcome=row.outcome,
                explanation_template=row.explanation_template,
                conditions=dict(row.conditions or {}),
                priority=row.priority,
                jurisdiction_id=row.jurisdiction_id,
                license_type_id=row.license_type_id,
                filing_channels=tuple(row.filing_channels or ()),
                required_facts=tuple(row.required_facts or ()),
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                requires_counsel_review=row.requires_counsel_review,
                enabled=row.enabled,
                citations=tuple(citations.get(row.id, ())),
            )
            for row in rows
        ]

    async def create_assessment(
        self,
        *,
        actor: CurrentActor,
        legal_entity_id: uuid.UUID,
        operating_profile_id: uuid.UUID,
        requested_jurisdictions: list[uuid.UUID],
        assessment_type: str | None = None,
        extra_facts: dict[str, Any] | None = None,
        effective_date: date | None = None,
        rule_set_name: str | None = None,
        commit: bool = True,
    ) -> RequirementAssessment:
        entity = await self.session.get(LegalEntity, legal_entity_id)
        profile = await self.session.get(OperatingProfile, operating_profile_id)
        if entity is None or profile is None:
            raise NotFoundError("Legal entity or operating profile not found.")
        if profile.legal_entity_id != legal_entity_id:
            raise StateConflictError("The operating profile belongs to a different legal entity.")
        if profile.status != "ACTIVE":
            raise StateConflictError(
                "Assessments must run against an ACTIVE operating profile version."
            )
        if not requested_jurisdictions:
            raise StateConflictError("At least one jurisdiction must be requested.")

        rule_set = await self._load_active_rule_set(rule_set_name)
        # Profile facts form the base; explicit extras override for what-if runs.
        facts: dict[str, Any] = dict(profile.facts or {})
        facts.update(extra_facts or {})

        fingerprint = content_sha256(
            {
                "profile": str(profile.id),
                "profile_version": profile.version,
                "facts": facts,
                "rule_set": f"{rule_set.name}:{rule_set.version}",
                "jurisdictions": sorted(str(j) for j in requested_jurisdictions),
                "effective_date": (effective_date or utcnow().date()).isoformat(),
            }
        )
        assessment = RequirementAssessment(
            assessment_key=f"{entity.entity_key}-{utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            legal_entity_id=legal_entity_id,
            operating_profile_id=operating_profile_id,
            assessment_type=assessment_type or AssessmentType.PERIODIC_REVIEW.value,
            status=AssessmentStatus.DRAFT.value,
            requested_jurisdictions=list(requested_jurisdictions),
            input_facts=facts,
            input_fingerprint=fingerprint,
            rule_set_id=rule_set.id,
            effective_date=effective_date or utcnow().date(),
            created_by_actor=actor.actor_id,
        )
        self.session.add(assessment)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_assessment",
            entity_id=assessment.id,
            action="assessment_created",
            after={
                "jurisdiction_count": len(requested_jurisdictions),
                "rule_set": f"{rule_set.name}:{rule_set.version}",
            },
        )
        if commit:
            await self.session.commit()
        REQUIREMENT_ASSESSMENTS_TOTAL.inc()
        return assessment

    async def evaluate(
        self,
        assessment_id: uuid.UUID,
        *,
        actor: CurrentActor | None = None,
        commit: bool = True,
    ) -> list[RequirementAssessmentResult]:
        """Evaluate every requested jurisdiction and store immutable results."""
        assessment = await self.session.get(RequirementAssessment, assessment_id)
        if assessment is None:
            raise NotFoundError("Assessment not found.")
        if assessment.status in (
            AssessmentStatus.APPROVED.value,
            AssessmentStatus.SUPERSEDED.value,
        ):
            raise StateConflictError(
                f"An {assessment.status} assessment is immutable. Create a new assessment."
            )
        entity = await self.session.get(LegalEntity, assessment.legal_entity_id)
        rules = await self._load_rules(assessment.rule_set_id)

        # Clear any prior draft results so re-evaluation is not additive.
        existing = list(
            await self.session.scalars(
                select(RequirementAssessmentResult).where(
                    RequirementAssessmentResult.assessment_id == assessment.id
                )
            )
        )
        for row in existing:
            await self.session.delete(row)
        await self.session.flush()

        policy = EvaluationSettings(
            require_human_review=self.settings.licensing_require_human_review,
            require_counsel_for_not_required=(
                self.settings.licensing_require_counsel_for_not_required
            ),
        )
        results: list[RequirementAssessmentResult] = []
        counsel_needed = False
        for jurisdiction_id in assessment.requested_jurisdictions:
            jurisdiction = await self.session.get(Jurisdiction, jurisdiction_id)
            if jurisdiction is None:
                continue
            outcome = evaluate_jurisdiction(
                jurisdiction_id=jurisdiction_id,
                jurisdiction_name=jurisdiction.name,
                license_type_id=None,
                facts=dict(assessment.input_facts or {}),
                rules=rules,
                when=assessment.effective_date or utcnow().date(),
                settings=policy,
                in_scope=bool(entity and entity.is_in_scope),
            )
            counsel_needed = counsel_needed or outcome.requires_counsel_review
            record = RequirementAssessmentResult(
                assessment_id=assessment.id,
                jurisdiction_id=jurisdiction_id,
                license_type_id=outcome.license_type_id,
                outcome=outcome.outcome,
                filing_channels=list(outcome.filing_channels),
                explanation=outcome.explanation,
                facts_used=outcome.facts_used,
                missing_facts=list(outcome.missing_facts),
                matched_rule_ids=list(outcome.matched_rule_ids),
                source_citations=list(outcome.source_citations),
                source_freshness_status=outcome.source_freshness_status,
                conflicting_rule_ids=list(outcome.conflicting_rule_ids),
                requires_human_review=outcome.requires_human_review,
                requires_counsel_review=outcome.requires_counsel_review,
            )
            self.session.add(record)
            results.append(record)

        assessment.status = (
            AssessmentStatus.COUNSEL_REVIEW.value
            if counsel_needed
            else AssessmentStatus.EVALUATED.value
        )
        assessment.evaluated_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_assessment",
            entity_id=assessment.id,
            action="assessment_evaluated",
            after={"results": len(results), "status": assessment.status},
        )
        if commit:
            await self.session.commit()
        await self.refresh_metrics()
        return results

    async def approve(
        self,
        assessment_id: uuid.UUID,
        *,
        actor: CurrentActor,
        notes: str | None = None,
        commit: bool = True,
    ) -> RequirementAssessment:
        """Approve an assessment. Every result must be individually reviewed first."""
        assessment = await self.session.get(RequirementAssessment, assessment_id)
        if assessment is None:
            raise NotFoundError("Assessment not found.")
        if assessment.status not in (
            AssessmentStatus.EVALUATED.value,
            AssessmentStatus.PENDING_REVIEW.value,
            AssessmentStatus.COUNSEL_REVIEW.value,
        ):
            raise StateConflictError(f"An assessment in {assessment.status} cannot be approved.")

        results = list(
            await self.session.scalars(
                select(RequirementAssessmentResult).where(
                    RequirementAssessmentResult.assessment_id == assessment.id
                )
            )
        )
        if not results:
            raise StateConflictError("Evaluate the assessment before approving it.")

        unreviewed = [r for r in results if r.reviewed_by_actor is None]
        if unreviewed:
            raise StateConflictError(
                "Every result must be reviewed before the assessment is approved.",
                details={"unreviewed_result_count": len(unreviewed)},
            )
        outstanding_counsel = [
            r for r in results if r.requires_counsel_review and r.reviewed_at is None
        ]
        if outstanding_counsel:
            raise StateConflictError(
                "Results flagged for counsel review need a recorded counsel decision.",
                details={"counsel_pending_count": len(outstanding_counsel)},
            )

        assessment.status = AssessmentStatus.APPROVED.value
        assessment.reviewed_by_actor = actor.actor_id
        assessment.reviewed_at = utcnow()
        assessment.review_notes = notes[:2000] if notes else None
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_assessment",
            entity_id=assessment.id,
            action="assessment_approved",
            after={"result_count": len(results)},
        )
        if commit:
            await self.session.commit()
        return assessment

    async def review_result(
        self,
        result_id: uuid.UUID,
        *,
        actor: CurrentActor,
        reviewed_outcome: str | None = None,
        notes: str | None = None,
        counsel_decision: bool = False,
        commit: bool = True,
    ) -> RequirementAssessmentResult:
        """Record a human review decision on one result."""
        result = await self.session.get(RequirementAssessmentResult, result_id)
        if result is None:
            raise NotFoundError("Assessment result not found.")
        if result.requires_counsel_review and not counsel_decision:
            raise StateConflictError(
                "This result requires the dedicated counsel-review action and "
                "cannot be finalized by a general reviewer."
            )
        if reviewed_outcome is not None and reviewed_outcome not in {
            member.value for member in RequirementOutcome
        }:
            raise StateConflictError(f"Unknown outcome {reviewed_outcome!r}.")
        result.reviewed_outcome = reviewed_outcome
        result.reviewer_notes = notes[:2000] if notes else result.reviewer_notes
        result.reviewed_by_actor = actor.actor_id
        result.reviewed_at = utcnow()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_assessment_result",
            entity_id=result.id,
            action=(
                "assessment_result_counsel_reviewed"
                if counsel_decision
                else "assessment_result_reviewed"
            ),
            after={
                "reviewed_outcome": reviewed_outcome,
                "outcome": result.outcome,
                "counsel_decision": counsel_decision,
            },
        )
        if commit:
            await self.session.commit()
        return result

    async def request_counsel_review(
        self, result_id: uuid.UUID, *, actor: CurrentActor, reason: str, commit: bool = True
    ) -> RequirementAssessmentResult:
        result = await self.session.get(RequirementAssessmentResult, result_id)
        if result is None:
            raise NotFoundError("Assessment result not found.")
        result.requires_counsel_review = True
        result.reviewed_outcome = None
        result.reviewed_by_actor = None
        result.reviewed_at = None
        result.reviewer_notes = (
            f"{result.reviewer_notes}\n{reason}" if result.reviewer_notes else reason
        )[:2000]
        assessment = await self.session.get(RequirementAssessment, result.assessment_id)
        if assessment is not None and assessment.status != AssessmentStatus.APPROVED.value:
            assessment.status = AssessmentStatus.COUNSEL_REVIEW.value
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_assessment_result",
            entity_id=result.id,
            action="counsel_review_requested",
            after={"reason_recorded": True},
        )
        if commit:
            await self.session.commit()
        return result

    async def override_result(
        self,
        result_id: uuid.UUID,
        *,
        actor: CurrentActor,
        overridden_outcome: str,
        reason: str,
        authority: str,
        source_reference: str | None = None,
        valid_from: date | None = None,
        valid_to: date | None = None,
        commit: bool = True,
    ) -> AssessmentOverride:
        """Record a human override of a computed outcome."""
        result = await self.session.get(RequirementAssessmentResult, result_id)
        if result is None:
            raise NotFoundError("Assessment result not found.")
        if overridden_outcome not in {member.value for member in RequirementOutcome}:
            raise StateConflictError(f"Unknown outcome {overridden_outcome!r}.")
        if authority not in {member.value for member in OverrideAuthority}:
            raise StateConflictError(f"Unknown override authority {authority!r}.")
        if not reason or len(reason.strip()) < 10:
            raise StateConflictError("An override requires a substantive documented reason.")
        # Declaring "not required" by override needs legal, not managerial, authority.
        if overridden_outcome == RequirementOutcome.LIKELY_NOT_REQUIRED.value and authority == (
            OverrideAuthority.COMPLIANCE_MANAGER.value
        ):
            raise StateConflictError(
                "Overriding to 'not required' requires counsel or written regulator "
                "guidance as the authority."
            )
        if overridden_outcome == RequirementOutcome.LIKELY_NOT_REQUIRED.value and not (
            source_reference and source_reference.strip()
        ):
            raise StateConflictError(
                "A 'not required' override must cite the counsel memo or written "
                "regulator guidance supporting it."
            )

        override = AssessmentOverride(
            assessment_result_id=result.id,
            original_outcome=result.outcome,
            overridden_outcome=overridden_outcome,
            reason=reason.strip()[:2000],
            authority=authority,
            approved_by_actor=actor.actor_id,
            source_reference=source_reference,
            valid_from=valid_from or utcnow().date(),
            valid_to=valid_to,
        )
        self.session.add(override)
        result.reviewed_outcome = overridden_outcome
        result.reviewed_by_actor = actor.actor_id
        result.reviewed_at = utcnow()
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="assessment_override",
            entity_id=override.id,
            action="assessment_result_overridden",
            before={"outcome": result.outcome},
            after={"overridden_outcome": overridden_outcome, "authority": authority},
        )
        if commit:
            await self.session.commit()
        return override

    async def effective_outcome(self, result_id: uuid.UUID) -> dict[str, Any]:
        """Resolve the governing outcome, honouring override expiry."""
        result = await self.session.get(RequirementAssessmentResult, result_id)
        if result is None:
            raise NotFoundError("Assessment result not found.")
        today = utcnow().date()
        overrides = list(
            await self.session.scalars(
                select(AssessmentOverride)
                .where(
                    AssessmentOverride.assessment_result_id == result.id,
                    AssessmentOverride.revoked_at.is_(None),
                )
                .order_by(AssessmentOverride.created_at.desc())
            )
        )
        active = next(
            (
                o
                for o in overrides
                if (o.valid_from is None or o.valid_from <= today)
                and (o.valid_to is None or o.valid_to >= today)
            ),
            None,
        )
        expired = [o for o in overrides if o.valid_to is not None and o.valid_to < today]
        return {
            "computed_outcome": result.outcome,
            "reviewed_outcome": result.reviewed_outcome,
            # An expired override stops governing; the advisory outcome returns.
            "effective_outcome": (
                active.overridden_outcome if active else (result.reviewed_outcome or result.outcome)
            ),
            "override_active": active is not None,
            "override_expired_count": len(expired),
            "requires_human_review": result.requires_human_review,
            "requires_counsel_review": result.requires_counsel_review,
            "advisory_only": True,
        }

    async def refresh_metrics(self) -> None:
        pending = (
            await self.session.scalar(
                select(func.count())
                .select_from(RequirementAssessmentResult)
                .where(
                    RequirementAssessmentResult.requires_counsel_review.is_(True),
                    RequirementAssessmentResult.reviewed_at.is_(None),
                )
            )
            or 0
        )
        REQUIREMENT_RESULTS_COUNSEL_REVIEW.set(pending)
