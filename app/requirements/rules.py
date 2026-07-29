"""In-memory rule representation and effective-date resolution.

Kept separate from the ORM so the evaluator can be exercised with plain data
structures — no database, no session, no fixtures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.requirements.conditions import (
    RuleValidationError,
    collect_fact_paths,
    validate_conditions,
)
from app.requirements.taxonomy import RequirementOutcome


@dataclass(frozen=True, slots=True)
class SourceCitation:
    """Denormalized citation captured at evaluation time.

    Copied rather than referenced so an approved result renders identically
    forever, even if the source is later retired or re-verified.
    """

    source_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    title: str
    authority_level: str
    source_type: str
    official_url: str | None = None
    snapshot_version: int | None = None
    last_verified_at: str | None = None
    effective_date: str | None = None
    citation_detail: str | None = None
    freshness_status: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": str(self.source_id) if self.source_id else None,
            "snapshot_id": str(self.snapshot_id) if self.snapshot_id else None,
            "title": self.title,
            "authority_level": self.authority_level,
            "source_type": self.source_type,
            "official_url": self.official_url,
            "snapshot_version": self.snapshot_version,
            "last_verified_at": self.last_verified_at,
            "effective_date": self.effective_date,
            "citation_detail": self.citation_detail,
            "freshness_status": self.freshness_status,
        }


@dataclass(frozen=True, slots=True)
class Rule:
    """A single evaluable requirement rule."""

    id: uuid.UUID
    rule_key: str
    outcome: str
    explanation_template: str
    conditions: dict[str, Any]
    priority: int = 100
    jurisdiction_id: uuid.UUID | None = None
    license_type_id: uuid.UUID | None = None
    filing_channels: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    effective_from: date | None = None
    effective_to: date | None = None
    requires_counsel_review: bool = False
    enabled: bool = True
    citations: tuple[SourceCitation, ...] = field(default_factory=tuple)

    def is_effective_on(self, when: date) -> bool:
        if self.effective_from and when < self.effective_from:
            return False
        return not (self.effective_to and when > self.effective_to)

    @property
    def specificity(self) -> int:
        """Higher means more specific. Used to order specific before broad rules."""
        return (1 if self.jurisdiction_id else 0) + (1 if self.license_type_id else 0)

    def referenced_facts(self) -> set[str]:
        """Union of declared required facts and facts the conditions reference."""
        return set(self.required_facts) | collect_fact_paths(self.conditions)

    def validate(self) -> None:
        validate_conditions(self.conditions)
        if self.outcome not in {member.value for member in RequirementOutcome}:
            raise RuleValidationError(f"Unknown outcome {self.outcome!r}.")
        if not self.explanation_template.strip():
            raise RuleValidationError("Every rule must carry an explanation template.")


def resolve_effective_rules(
    rules: list[Rule],
    *,
    when: date,
    jurisdiction_id: uuid.UUID | None = None,
    license_type_id: uuid.UUID | None = None,
) -> list[Rule]:
    """Filter to enabled, in-force, in-scope rules, ordered specific-first.

    A rule with a NULL jurisdiction or licence type is a catch-all that applies to
    everything; a rule naming them applies only to that scope. Sorting by
    descending specificity then ascending priority means the narrowest applicable
    statement is considered before a general fallback.
    """
    applicable = [
        rule
        for rule in rules
        if rule.enabled
        and rule.is_effective_on(when)
        and (rule.jurisdiction_id is None or rule.jurisdiction_id == jurisdiction_id)
        and (rule.license_type_id is None or rule.license_type_id == license_type_id)
    ]
    return sorted(applicable, key=lambda r: (-r.specificity, r.priority, r.rule_key))


__all__ = ["Rule", "SourceCitation", "resolve_effective_rules"]
