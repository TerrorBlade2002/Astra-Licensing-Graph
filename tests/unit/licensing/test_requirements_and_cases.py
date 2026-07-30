from __future__ import annotations

import uuid
from datetime import date

from app.licensing.enums import CaseStage
from app.licensing.stages import initial_stage, next_stages, validate_transition
from app.requirements.evaluator import EvaluationSettings, evaluate_jurisdiction
from app.requirements.rules import Rule, SourceCitation


def test_case_cannot_skip_evidence_gated_stages() -> None:
    check = validate_transition(
        from_stage=CaseStage.DUE_IDENTIFIED.value,
        to_stage=CaseStage.SUBMITTED_TO_REGULATOR.value,
    )
    assert not check.allowed


def test_signature_required_blocks_submission() -> None:
    check = validate_transition(
        from_stage=CaseStage.SUBMISSION_PENDING.value,
        to_stage=CaseStage.SUBMITTED_TO_VENDOR.value,
        evidence={"submission_reference": "synthetic-reference"},
        signature_required=True,
        signature_recorded=False,
    )
    assert not check.allowed
    assert "signature" in check.reason.lower()


def test_completion_needs_renewed_evidence_or_close_reason() -> None:
    assert not validate_transition(
        from_stage=CaseStage.INVENTORY_UPDATE_PENDING.value,
        to_stage=CaseStage.COMPLETED.value,
    ).allowed
    assert validate_transition(
        from_stage=CaseStage.INVENTORY_UPDATE_PENDING.value,
        to_stage=CaseStage.COMPLETED.value,
        close_reason="Synthetic obligation was formally withdrawn.",
    ).allowed


def test_initial_stage_and_next_stages_are_explicit() -> None:
    assert initial_stage() == CaseStage.DUE_IDENTIFIED.value
    assert CaseStage.CASE_PLANNING.value in next_stages(initial_stage())


def _citation() -> SourceCitation:
    return SourceCitation(
        source_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        title="Synthetic official checklist",
        authority_level="OFFICIAL_PRIMARY",
        source_type="REGULATOR_PDF",
        snapshot_version=1,
        last_verified_at="2026-01-01",
        freshness_status="FRESH",
    )


def test_requirement_result_keeps_nmls_and_supplemental_channels_separate() -> None:
    jurisdiction = uuid.uuid4()
    rule = Rule(
        id=uuid.uuid4(),
        rule_key="synthetic-third-party-collection",
        jurisdiction_id=jurisdiction,
        outcome="LIKELY_REQUIRED",
        explanation_template="Third-party consumer collection is recorded.",
        conditions={"fact": "activities", "op": "contains", "value": "third_party_collection"},
        filing_channels=("NMLS", "STATE_PORTAL"),
        citations=(_citation(),),
    )
    result = evaluate_jurisdiction(
        jurisdiction_id=jurisdiction,
        jurisdiction_name="Synthetic State",
        license_type_id=None,
        facts={"activities": ["third_party_collection"]},
        rules=[rule],
        when=date(2026, 1, 1),
        settings=EvaluationSettings(require_human_review=True),
    )
    assert result.outcome == "LIKELY_REQUIRED"
    assert result.filing_channels == ["NMLS", "STATE_PORTAL"]
    assert result.requires_human_review
    assert result.source_citations


def test_missing_material_fact_never_becomes_false() -> None:
    jurisdiction = uuid.uuid4()
    rule = Rule(
        id=uuid.uuid4(),
        rule_key="synthetic-payment-handling",
        jurisdiction_id=jurisdiction,
        outcome="LIKELY_REQUIRED",
        explanation_template="Direct payment handling is material.",
        conditions={"fact": "payment.accepts_direct", "op": "is_true"},
        required_facts=("payment.accepts_direct",),
        citations=(_citation(),),
    )
    result = evaluate_jurisdiction(
        jurisdiction_id=jurisdiction,
        jurisdiction_name="Synthetic State",
        license_type_id=None,
        facts={},
        rules=[rule],
        when=date(2026, 1, 1),
    )
    assert result.outcome == "INSUFFICIENT_INFORMATION"
    assert "payment.accepts_direct" in result.missing_facts


def test_equal_precedence_conflict_forces_counsel_review() -> None:
    jurisdiction = uuid.uuid4()
    common = {
        "jurisdiction_id": jurisdiction,
        "explanation_template": "Synthetic matched rule.",
        "conditions": {"fact": "active", "op": "is_true"},
        "priority": 1,
        "citations": (_citation(),),
    }
    rules = [
        Rule(id=uuid.uuid4(), rule_key="required", outcome="LIKELY_REQUIRED", **common),
        Rule(id=uuid.uuid4(), rule_key="not-required", outcome="LIKELY_NOT_REQUIRED", **common),
    ]
    result = evaluate_jurisdiction(
        jurisdiction_id=jurisdiction,
        jurisdiction_name="Synthetic State",
        license_type_id=None,
        facts={"active": True},
        rules=rules,
        when=date(2026, 1, 1),
    )
    assert result.outcome == "COUNSEL_REVIEW"
    assert result.requires_counsel_review
    assert len(result.conflicting_rule_ids) == 2
