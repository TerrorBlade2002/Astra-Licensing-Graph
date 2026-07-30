from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta

from app.core.crypto import Keyring, SensitiveValueCipher
from app.documents.enums import ApprovalStatus, ConfidentialityLevel, LifecycleStatus, StorageStatus
from app.forms.filling import verify_signed_document
from app.forms.inspection import classify_field_type, infer_sensitivity
from app.information_registry.scoping import (
    ReuseRejection,
    UsageContext,
    ValueScope,
    evaluate_reuse,
    permitted_for_ai,
)
from app.packets.manifests import build_archive, verify_entry_hash
from app.packets.matching import (
    CandidateDocument,
    ItemRequirement,
    MatchContext,
    evaluate_candidate,
)


def test_ciphertext_is_bound_to_owning_record() -> None:
    cipher = SensitiveValueCipher(Keyring.generate())
    sealed = cipher.encrypt(
        {"value": "synthetic secret"}, entity_type="information_value", entity_id="one"
    )
    assert cipher.decrypt_json(sealed, entity_type="information_value", entity_id="one") == {
        "value": "synthetic secret"
    }
    try:
        cipher.decrypt_json(sealed, entity_type="information_value", entity_id="two")
    except Exception:
        pass
    else:
        raise AssertionError("ciphertext was reusable across records")


def test_wrong_entity_and_expired_values_cannot_be_reused() -> None:
    decision = evaluate_reuse(
        status="APPROVED",
        reusable_policy="ENTITY_ONLY",
        sensitivity="INTERNAL",
        scope=ValueScope(legal_entity_id=uuid.uuid4()),
        context=UsageContext(legal_entity_id=uuid.uuid4()),
        owner_actor="synthetic-owner",
        approved_at=datetime.now(UTC) - timedelta(days=400),
        freshness_days=30,
    )
    assert not decision.usable
    assert ReuseRejection.WRONG_ENTITY in decision.reasons
    assert ReuseRejection.STALE in decision.reasons


def test_only_internal_information_is_permitted_for_ai() -> None:
    assert permitted_for_ai("INTERNAL")
    assert not permitted_for_ai("CONFIDENTIAL")
    assert not permitted_for_ai("HIGHLY_RESTRICTED")


def _candidate(**overrides: object) -> CandidateDocument:
    digest = hashlib.sha256(b"synthetic document").hexdigest()
    values = {
        "document_id": uuid.uuid4(),
        "document_version_id": uuid.uuid4(),
        "document_type": "CERTIFICATE_GOOD_STANDING",
        "canonical_title": "Synthetic certificate",
        "filename": "synthetic.pdf",
        "content_sha256": digest,
        "version_sha256": digest,
        "lifecycle_status": LifecycleStatus.ACTIVE.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "confidentiality_level": ConfidentialityLevel.INTERNAL.value,
        "storage_status": StorageStatus.AVAILABLE.value,
        "legal_entity": "synthetic-entity",
        "jurisdiction": "SS",
        "expiry_date": date(2027, 1, 1),
        "approved_for_reuse": True,
        "storage_uri": "graph://synthetic-drive/synthetic-item",
    }
    values.update(overrides)
    return CandidateDocument(**values)


def test_packet_candidate_must_be_correct_entity_and_hash_valid() -> None:
    requirement = ItemRequirement(
        item_key="good-standing",
        document_type="CERTIFICATE_GOOD_STANDING",
        selection_policy={"require_reuse_approval": True},
    )
    context = MatchContext(
        legal_entity_key="synthetic-entity",
        jurisdiction_key="SS",
        today=date(2026, 1, 1),
    )
    assert evaluate_candidate(_candidate(), requirement, context) == []
    wrong = evaluate_candidate(
        _candidate(legal_entity="other-entity", version_sha256="0" * 64),
        requirement,
        context,
    )
    codes = {item.code for item in wrong}
    assert "DOCUMENT_WRONG_ENTITY" in codes
    assert "DOCUMENT_HASH_MISMATCH" in codes


def test_expired_or_quarantined_document_is_blocked() -> None:
    requirement = ItemRequirement(
        item_key="good-standing", document_type="CERTIFICATE_GOOD_STANDING"
    )
    context = MatchContext(legal_entity_key="synthetic-entity", today=date(2026, 1, 1))
    problems = evaluate_candidate(
        _candidate(
            lifecycle_status=LifecycleStatus.QUARANTINED.value,
            expiry_date=date(2025, 1, 1),
        ),
        requirement,
        context,
    )
    assert problems


def test_packet_archive_is_deterministic_and_hash_pinned() -> None:
    content = b"synthetic governed document"
    manifest = {
        "packet_key": "SYNTHETIC-PACKET",
        "packet_version": 1,
        "included": [{"filename_in_archive": "01-evidence.pdf"}],
    }
    first, first_hash = build_archive(
        manifest=manifest,
        files={"01-evidence.pdf": content},
        cover_sheet="Synthetic cover sheet",
    )
    second, second_hash = build_archive(
        manifest=manifest,
        files={"01-evidence.pdf": content},
        cover_sheet="Synthetic cover sheet",
    )
    assert first == second
    assert first_hash == second_hash
    assert verify_entry_hash(content, hashlib.sha256(content).hexdigest())
    assert not verify_entry_hash(content + b"changed", hashlib.sha256(content).hexdigest())


def test_signature_fields_are_identified_and_never_auto_signed() -> None:
    assert classify_field_type("authorized_signature") == "SIGNATURE"
    assert infer_sensitivity("social_security_number") == "HIGHLY_RESTRICTED"
    ok, _ = verify_signed_document(
        approved_draft_sha256="a" * 64,
        signed_content_sha256="a" * 64,
        signed_page_count=1,
    )
    assert not ok
    ok, _ = verify_signed_document(
        approved_draft_sha256="a" * 64,
        signed_content_sha256="b" * 64,
        signed_page_count=1,
    )
    assert ok
