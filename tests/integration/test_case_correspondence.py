"""Correspondence linking end to end: propose, decide, and read the timeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.exceptions import StateConflictError
from app.domain.enums import ActorType, ProcessingState
from app.licensing.enums import (
    CaseEmailLinkStatus,
    CasePriority,
    CaseStage,
    CaseStatus,
    CaseType,
    EntityStatus,
    EntityType,
    FilingChannel,
    JurisdictionType,
    LicenseCategory,
    LicenseStatus,
    ObligationStatus,
    ObligationType,
    SourceConfidence,
)
from app.models import (
    Classification,
    ComplianceCase,
    ComplianceObligation,
    Email,
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicenseType,
    Mailbox,
)
from app.services.case_email_link_service import CaseEmailLinkService
from app.services.renewal_timeline_service import RenewalTimelineService


def _actor(actor_id: str = "reviewer-1") -> CurrentActor:
    return CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        tenant_id="test",
        object_id=actor_id,
        roles=("Licensing.Reviewer",),
    )


async def _seed(session: AsyncSession, *, license_number: str = "MB-778899") -> dict[str, object]:
    entity = LegalEntity(
        entity_key=f"entity-{uuid.uuid4().hex[:8]}",
        legal_name="Astra Test Holdings",
        entity_type=EntityType.LLC.value,
        status=EntityStatus.ACTIVE.value,
    )
    other_entity = LegalEntity(
        entity_key=f"entity-{uuid.uuid4().hex[:8]}",
        legal_name="Unrelated Sibling Entity",
        entity_type=EntityType.LLC.value,
        status=EntityStatus.ACTIVE.value,
    )
    jurisdiction = Jurisdiction(
        jurisdiction_key="GA",
        name="Georgia",
        jurisdiction_type=JurisdictionType.STATE.value,
    )
    license_type = LicenseType(
        license_type_key=f"lt-{uuid.uuid4().hex[:8]}",
        name="Collection Agency",
        category=LicenseCategory.COLLECTION_AGENCY.value,
    )
    session.add_all([entity, other_entity, jurisdiction, license_type])
    await session.flush()

    licence = LicenseInventory(
        license_key=f"lic-{uuid.uuid4().hex[:8]}",
        legal_entity_id=entity.id,
        jurisdiction_id=jurisdiction.id,
        license_type_id=license_type.id,
        license_number=license_number,
        filing_channel=FilingChannel.STATE_PORTAL.value,
        current_status=LicenseStatus.ACTIVE.value,
        source_confidence=SourceConfidence.VERIFIED_DOCUMENT.value,
        expiration_date=(datetime.now(UTC) + timedelta(days=45)).date(),
    )
    session.add(licence)
    await session.flush()

    obligation = ComplianceObligation(
        obligation_key=f"ob-{uuid.uuid4().hex[:8]}",
        legal_entity_id=entity.id,
        license_id=licence.id,
        obligation_type=ObligationType.LICENSE_RENEWAL.value,
        title="Georgia collection agency renewal",
        status=ObligationStatus.ACTIVE.value,
        next_due_date=(datetime.now(UTC) + timedelta(days=45)).date(),
    )
    session.add(obligation)
    await session.flush()

    case = ComplianceCase(
        case_key=f"case-{uuid.uuid4().hex[:8]}",
        obligation_id=obligation.id,
        legal_entity_id=entity.id,
        license_id=licence.id,
        case_type=CaseType.LICENSE_RENEWAL.value,
        current_stage=CaseStage.CASE_PLANNING.value,
        status=CaseStatus.OPEN.value,
        priority=CasePriority.NORMAL.value,
        statutory_due_date=(datetime.now(UTC) + timedelta(days=45)).date(),
    )
    session.add(case)

    mailbox = Mailbox(
        address=f"licensing-{uuid.uuid4().hex[:6]}@example.invalid",
        display_name="Licensing",
    )
    session.add(mailbox)
    await session.flush()

    email = Email(
        mailbox_id=mailbox.id,
        graph_message_id=f"msg-{uuid.uuid4().hex}",
        conversation_id=f"conv-{uuid.uuid4().hex[:12]}",
        subject="Renewal invoice for licence MB-778899",
        sender_email="renewals@vendor.invalid",
        received_at=datetime.now(UTC),
        processing_state=ProcessingState.CLASSIFIED.value,
        has_attachments=False,
    )
    session.add(email)
    await session.flush()

    classification = Classification(
        email_id=email.id,
        version=1,
        schema_version="1.0",
        vendor="Test Vendor",
        email_type="renewal_notice",
        states=["GA"],
        license_types=["Collection Agency"],
        license_numbers=[license_number],
        action_required=True,
        requires_human_review=True,
        classification_method="deterministic_rules",
        evidence={},
        is_current=True,
    )
    session.add(classification)
    await session.commit()
    return {"case": case, "email": email, "classification": classification, "license": licence}


async def test_matching_proposes_the_case_whose_license_number_is_quoted(
    session: AsyncSession,
) -> None:
    seeded = await _seed(session)
    service = CaseEmailLinkService(session)
    links = await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()

    assert len(links) == 1
    link = links[0]
    assert link.compliance_case_id == seeded["case"].id  # type: ignore[attr-defined]
    assert link.link_status == CaseEmailLinkStatus.PROPOSED.value
    codes = {signal["code"] for signal in link.match_reasons["signals"]}
    assert "LICENSE_NUMBER" in codes


async def test_a_proposal_is_not_evidence_until_confirmed(session: AsyncSession) -> None:
    """The thread and timeline stay empty while the link is only proposed."""
    seeded = await _seed(session)
    service = CaseEmailLinkService(session)
    await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()
    case_id = seeded["case"].id  # type: ignore[attr-defined]

    assert await service.thread_for_case(case_id) == []
    timeline = await RenewalTimelineService(session).build(seeded["license"].id)  # type: ignore[attr-defined]
    assert [e for e in timeline.entries if e.category == "EMAIL_RECEIVED"] == []


async def test_confirmation_attaches_the_thread_and_records_the_reviewer(
    session: AsyncSession,
) -> None:
    seeded = await _seed(session)
    service = CaseEmailLinkService(session)
    links = await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()

    confirmed = await service.confirm(links[0].id, _actor(), reason="Matches the renewal notice.")
    await session.commit()

    assert confirmed.link_status == CaseEmailLinkStatus.CONFIRMED.value
    assert confirmed.decided_by_actor == "reviewer-1"

    case = await session.get(ComplianceCase, seeded["case"].id)  # type: ignore[attr-defined]
    assert case is not None
    # The first confirmed thread becomes the case's primary conversation.
    assert case.primary_conversation_id == seeded["email"].conversation_id  # type: ignore[attr-defined]

    thread = await service.thread_for_case(case.id)
    assert [message.id for message in thread] == [seeded["email"].id]  # type: ignore[attr-defined]

    timeline = await RenewalTimelineService(session).build(seeded["license"].id)  # type: ignore[attr-defined]
    received = [entry for entry in timeline.entries if entry.category == "EMAIL_RECEIVED"]
    assert len(received) == 1
    assert received[0].reference["confirmed_by"] == "reviewer-1"
    assert timeline.active_stage == CaseStage.CASE_PLANNING.value
    assert timeline.open_case_count == 1


async def test_a_rejected_link_stays_out_of_the_case_file(session: AsyncSession) -> None:
    seeded = await _seed(session)
    service = CaseEmailLinkService(session)
    links = await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()

    await service.reject(links[0].id, _actor(), reason="Different entity.")
    await session.commit()

    case_id = seeded["case"].id  # type: ignore[attr-defined]
    assert await service.thread_for_case(case_id) == []
    # A decided link cannot be flipped by a second reviewer without a new proposal.
    with pytest.raises(StateConflictError):
        await service.confirm(links[0].id, _actor("reviewer-2"))


async def test_reprocessing_an_email_does_not_duplicate_or_revive_decisions(
    session: AsyncSession,
) -> None:
    seeded = await _seed(session)
    service = CaseEmailLinkService(session)
    links = await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()
    await service.reject(links[0].id, _actor(), reason="Not this case.")
    await session.commit()

    again = await service.propose_for_email(
        seeded["email"],  # type: ignore[arg-type]
        classification=seeded["classification"],  # type: ignore[arg-type]
    )
    await session.commit()

    assert again == []
    all_links = await service.links_for_case(seeded["case"].id)  # type: ignore[attr-defined]
    assert len(all_links) == 1
    assert all_links[0].link_status == CaseEmailLinkStatus.REJECTED.value
