"""The advisory requirement evaluator.

Pure logic: given facts, rules, and a freshness view, produce one immutable
advisory result per jurisdiction/licence-type pair. No database, no I/O.

Evaluation order follows section 10 of the milestone specification:

1. validate facts
2. identify missing material facts
3. resolve effective rules for the assessment date
4. evaluate specific rules before broad rules
5. detect conflicting results
6. collect filing channels
7. explain in plain language
8. attach citations
9. compute source freshness
10. mark human / counsel review

Conflict handling is deliberately conservative. When two in-scope rules of equal
specificity and priority disagree, the evaluator does **not** silently pick a
winner: it records both, escalates to the more cautious outcome, and flags counsel
review. Quietly resolving a genuine legal disagreement is exactly the failure mode
this system exists to prevent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.requirements.conditions import EvaluationTrace, Truth, evaluate
from app.requirements.explanations import build_explanation, render_template
from app.requirements.freshness import summarize
from app.requirements.rules import Rule, SourceCitation, resolve_effective_rules
from app.requirements.taxonomy import (
    AUTHORITATIVE_LEVELS,
    OUTCOME_CAUTION_RANK,
    RequirementOutcome,
    SourceFreshnessStatus,
)


@dataclass(frozen=True, slots=True)
class EvaluationSettings:
    """Policy knobs sourced from application settings."""

    require_human_review: bool = True
    require_counsel_for_not_required: bool = True
    #: When a matched rule's only citations are non-authoritative (vendor or
    #: internal), escalate rather than presenting it as a requirement.
    escalate_non_authoritative_sources: bool = True


@dataclass(slots=True)
class RuleMatch:
    rule: Rule
    truth: Truth
    statement: str


@dataclass(slots=True)
class JurisdictionResult:
    """One advisory result, ready to persist."""

    jurisdiction_id: uuid.UUID
    license_type_id: uuid.UUID | None
    outcome: str
    filing_channels: list[str]
    explanation: str
    facts_used: dict[str, Any]
    missing_facts: list[str]
    matched_rule_ids: list[uuid.UUID]
    conflicting_rule_ids: list[uuid.UUID]
    source_citations: list[dict[str, Any]]
    source_freshness_status: str
    requires_human_review: bool
    requires_counsel_review: bool
    #: Diagnostics for the UI; not a legal record.
    notes: list[str] = field(default_factory=list)


def _more_cautious(left: str, right: str) -> str:
    return (
        left if OUTCOME_CAUTION_RANK.get(left, 0) >= OUTCOME_CAUTION_RANK.get(right, 0) else right
    )


def evaluate_jurisdiction(
    *,
    jurisdiction_id: uuid.UUID,
    jurisdiction_name: str,
    license_type_id: uuid.UUID | None,
    facts: dict[str, Any],
    rules: list[Rule],
    when: date,
    freshness_by_snapshot: dict[uuid.UUID, str] | None = None,
    settings: EvaluationSettings | None = None,
    in_scope: bool = True,
) -> JurisdictionResult:
    """Evaluate every applicable rule for one jurisdiction and reconcile them."""
    policy = settings or EvaluationSettings()
    freshness_map = freshness_by_snapshot or {}

    if not in_scope:
        return JurisdictionResult(
            jurisdiction_id=jurisdiction_id,
            license_type_id=license_type_id,
            outcome=RequirementOutcome.OUT_OF_SCOPE.value,
            filing_channels=[],
            explanation=build_explanation(
                outcome=RequirementOutcome.OUT_OF_SCOPE.value,
                jurisdiction_name=jurisdiction_name,
                rule_statements=["The jurisdiction is outside the assessed footprint."],
                facts_used={},
                missing_facts=[],
                filing_channels=[],
                citations=[],
                freshness_status=SourceFreshnessStatus.NO_SOURCE.value,
            ),
            facts_used={},
            missing_facts=[],
            matched_rule_ids=[],
            conflicting_rule_ids=[],
            source_citations=[],
            source_freshness_status=SourceFreshnessStatus.NO_SOURCE.value,
            requires_human_review=policy.require_human_review,
            requires_counsel_review=False,
        )

    effective = resolve_effective_rules(
        rules, when=when, jurisdiction_id=jurisdiction_id, license_type_id=license_type_id
    )

    trace = EvaluationTrace()
    matches: list[RuleMatch] = []
    unknown_matches: list[RuleMatch] = []

    for rule in effective:
        truth = evaluate(rule.conditions, facts, trace)
        statement = render_template(rule.explanation_template, facts)
        if truth is Truth.TRUE:
            matches.append(RuleMatch(rule=rule, truth=truth, statement=statement))
        elif truth is Truth.UNKNOWN:
            unknown_matches.append(RuleMatch(rule=rule, truth=truth, statement=statement))

    # Facts a rule declared as material but which were never supplied. Declared
    # requirements matter even when short-circuit evaluation never touched them.
    declared_missing = sorted(
        {path for rule in effective for path in rule.required_facts if path not in trace.facts_used}
    )
    missing_facts = sorted(set(trace.missing_facts) | set(declared_missing))

    notes: list[str] = []
    conflicting_rule_ids: list[uuid.UUID] = []

    if not effective:
        outcome = RequirementOutcome.INSUFFICIENT_INFORMATION.value
        statements = ["No requirement rule covers this jurisdiction in the active rule set."]
        notes.append("no_rules_in_scope")
        chosen: list[RuleMatch] = []
    elif matches:
        # Highest specificity / lowest priority wins as the primary statement.
        primary = matches[0]
        outcome = primary.rule.outcome
        peers = [
            m
            for m in matches
            if m.rule.specificity == primary.rule.specificity
            and m.rule.priority == primary.rule.priority
            and m.rule.outcome != primary.rule.outcome
        ]
        if peers:
            # Genuine disagreement at equal authority: escalate, never arbitrate.
            conflicting_rule_ids = [primary.rule.id] + [m.rule.id for m in peers]
            for peer in peers:
                outcome = _more_cautious(outcome, peer.rule.outcome)
            outcome = _more_cautious(outcome, RequirementOutcome.COUNSEL_REVIEW.value)
            notes.append("conflicting_rules_equal_precedence")
        chosen = matches
        statements = [m.statement for m in matches]
        if unknown_matches:
            # A rule that would apply but for an unresolved fact keeps the answer
            # provisional even when another rule already matched.
            if outcome == RequirementOutcome.LIKELY_NOT_REQUIRED.value:
                outcome = RequirementOutcome.POSSIBLY_REQUIRED.value
                notes.append("downgraded_by_unresolved_rule")
            statements.extend(
                f"{m.statement} (unresolved: depends on facts not yet recorded)"
                for m in unknown_matches
            )
    elif unknown_matches:
        outcome = RequirementOutcome.INSUFFICIENT_INFORMATION.value
        chosen = unknown_matches
        statements = [
            f"{m.statement} (unresolved: depends on facts not yet recorded)"
            for m in unknown_matches
        ]
        notes.append("all_candidate_rules_unresolved")
    else:
        # Rules existed, none matched: a defensible "not required" signal.
        outcome = RequirementOutcome.LIKELY_NOT_REQUIRED.value
        chosen = []
        statements = [
            "No rule in the active rule set is triggered by the recorded facts.",
        ]

    # Filing channels are a union: an NMLS licence can also carry a state
    # supplement, and both must surface.
    channels: list[str] = []
    for match in chosen:
        for channel in match.rule.filing_channels:
            if channel not in channels:
                channels.append(channel)

    citations: list[dict[str, Any]] = []
    citation_freshness: list[str] = []
    seen_snapshots: set[tuple[uuid.UUID | None, uuid.UUID | None]] = set()
    has_authoritative = False
    for match in chosen:
        for citation in match.rule.citations:
            key = (citation.source_id, citation.snapshot_id)
            if key in seen_snapshots:
                continue
            seen_snapshots.add(key)
            status = (
                (freshness_map.get(citation.snapshot_id) if citation.snapshot_id else None)
                or citation.freshness_status
                or SourceFreshnessStatus.UNKNOWN.value
            )
            citation_freshness.append(status)
            payload = citation.to_payload()
            payload["freshness_status"] = status
            citations.append(payload)
            if citation.authority_level in AUTHORITATIVE_LEVELS:
                has_authoritative = True

    freshness_status = summarize(citation_freshness)

    counsel_reason: str | None = None
    requires_counsel = any(m.rule.requires_counsel_review for m in chosen)
    if requires_counsel:
        counsel_reason = "A matched rule is marked as requiring counsel review."

    if outcome == RequirementOutcome.COUNSEL_REVIEW.value:
        requires_counsel = True
        counsel_reason = counsel_reason or "Rules of equal precedence disagree."

    # A stale or never-verified source cannot support a confident answer.
    if freshness_status in (
        SourceFreshnessStatus.STALE.value,
        SourceFreshnessStatus.NO_SOURCE.value,
    ) and outcome in (
        RequirementOutcome.LIKELY_REQUIRED.value,
        RequirementOutcome.LIKELY_NOT_REQUIRED.value,
    ):
        outcome = (
            RequirementOutcome.POSSIBLY_REQUIRED.value
            if outcome == RequirementOutcome.LIKELY_REQUIRED.value
            else RequirementOutcome.COUNSEL_REVIEW.value
        )
        requires_counsel = True
        counsel_reason = "The cited sources are stale or absent."
        notes.append("downgraded_by_source_freshness")

    # Vendor-only or internal-only backing is operational guidance, not law.
    if (
        policy.escalate_non_authoritative_sources
        and chosen
        and citations
        and not has_authoritative
        and outcome
        in (
            RequirementOutcome.LIKELY_REQUIRED.value,
            RequirementOutcome.LIKELY_NOT_REQUIRED.value,
        )
    ):
        outcome = RequirementOutcome.POSSIBLY_REQUIRED.value
        requires_counsel = True
        counsel_reason = (
            "Only vendor or internal sources back this result; no official source is cited."
        )
        notes.append("no_authoritative_source")

    # Declaring "not required" is the highest-risk answer to get wrong.
    if (
        policy.require_counsel_for_not_required
        and outcome == RequirementOutcome.LIKELY_NOT_REQUIRED.value
    ):
        requires_counsel = True
        counsel_reason = counsel_reason or (
            "Policy requires counsel confirmation before recording 'not required'."
        )

    conflict_note = (
        "Rules of equal specificity and priority produced different outcomes; "
        "the more cautious outcome was recorded and counsel review was flagged."
        if conflicting_rule_ids
        else None
    )

    explanation = build_explanation(
        outcome=outcome,
        jurisdiction_name=jurisdiction_name,
        rule_statements=statements,
        facts_used=dict(trace.facts_used),
        missing_facts=missing_facts,
        filing_channels=channels,
        citations=citations,
        freshness_status=freshness_status,
        conflict_note=conflict_note,
        counsel_reason=counsel_reason,
    )

    return JurisdictionResult(
        jurisdiction_id=jurisdiction_id,
        license_type_id=license_type_id,
        outcome=outcome,
        filing_channels=channels,
        explanation=explanation,
        facts_used=dict(trace.facts_used),
        missing_facts=missing_facts,
        matched_rule_ids=[m.rule.id for m in chosen],
        conflicting_rule_ids=conflicting_rule_ids,
        source_citations=citations,
        source_freshness_status=freshness_status,
        # Human review is mandatory by policy; an unreviewed result is never a
        # determination and cannot seed a licence record.
        requires_human_review=policy.require_human_review or requires_counsel,
        requires_counsel_review=requires_counsel,
        notes=notes,
    )


__all__ = [
    "EvaluationSettings",
    "JurisdictionResult",
    "RuleMatch",
    "SourceCitation",
    "evaluate_jurisdiction",
]
