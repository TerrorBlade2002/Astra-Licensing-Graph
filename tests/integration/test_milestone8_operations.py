"""Milestone 8: migration, reconciliation, scheduler, and worker heartbeat.

These exercise the operations the go-live checklist depends on, against a real
PostgreSQL database and with no provider call of any kind.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.domain.enums import ActorType
from app.licensing.enums import (
    EntityStatus,
    EntityType,
    FilingChannel,
    JurisdictionType,
    LicenseCategory,
    LicenseStatus,
    SourceConfidence,
)
from app.models import (
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicenseType,
    LicensingJob,
    WorkerHeartbeat,
)
from app.models.mixins import utcnow
from app.services.migration_reconciliation import MigrationReconciliationService
from app.services.tracker_import_service import TrackerImportService
from app.workers.context import WorkerContext
from app.workers.runner import run_worker
from app.workers.scheduling import run_scheduler_cycle
from tests.conftest import make_test_settings

TRACKER_CSV = b"""Entity,State,License Type,Number,Status,Expires,Owner
Astra Test Holdings,Georgia,Collection Agency,GA-1001,Active,2027-03-31,alex.owner
Astra Test Holdings,Nevada,Collection Agency,NV-2002,Active,2026-09-30,alex.owner
"""

MAPPING = {
    "LEGAL_ENTITY": "Entity",
    "JURISDICTION": "State",
    "LICENSE_TYPE": "License Type",
    "LICENSE_NUMBER": "Number",
    "STATUS": "Status",
    "EXPIRATION_DATE": "Expires",
    "RESPONSIBLE_OWNER": "Owner",
}


def _actor() -> CurrentActor:
    return CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id="migration-operator",
        tenant_id="test",
        object_id="migration-operator",
        roles=("Licensing.Admin", "Licensing.Manager"),
    )


async def _seed_registry(session: AsyncSession) -> None:
    """The registry rows an import resolves against; imports never invent them."""
    session.add(
        LegalEntity(
            entity_key="astra-test-holdings",
            legal_name="Astra Test Holdings",
            entity_type=EntityType.LLC.value,
            status=EntityStatus.ACTIVE.value,
        )
    )
    for key, name in (("ga", "Georgia"), ("nv", "Nevada")):
        session.add(
            Jurisdiction(
                jurisdiction_key=key,
                name=name,
                jurisdiction_type=JurisdictionType.STATE.value,
            )
        )
    session.add(
        LicenseType(
            license_type_key="collection-agency",
            name="Collection Agency",
            category=LicenseCategory.COLLECTION_AGENCY.value,
        )
    )
    await session.commit()


# --------------------------------------------------------------- migrations


def test_migrations_are_repeatable_from_base(alembic_config: Config) -> None:
    """A clean database must reach head, and head must be re-appliable."""
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    # Running head again is the deployment's pre-deploy command on every
    # redeploy; it must be a no-op rather than an error.
    command.upgrade(alembic_config, "head")


async def test_head_revision_fits_the_version_table(session: AsyncSession) -> None:
    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    width = await session.scalar(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
        )
    )
    assert revision is not None
    assert width is not None and len(revision) <= int(width)


# ---------------------------------------------------- migration and reconcile


async def test_tracker_import_dry_run_then_apply_is_idempotent(
    session: AsyncSession, test_database_url: str
) -> None:
    settings = make_test_settings(test_database_url)
    await _seed_registry(session)
    service = TrackerImportService(session, settings)

    dry_run = await service.plan(
        actor=_actor(), filename="master-tracker.csv", content=TRACKER_CSV, mapping=MAPPING
    )
    assert dry_run["dry_run"] is True
    assert dry_run["counts"] == {"insert": 2, "update": 0, "skip": 0, "conflict": 0, "error": 0}
    # A dry run writes no inventory rows.
    assert await session.scalar(select(LicenseInventory.id).limit(1)) is None

    applied = await service.apply(
        uuid.UUID(str(dry_run["import_run_id"])), actor=_actor(), confirm=True
    )
    assert (applied["inserted"], applied["updated"], applied["errors"]) == (2, 0, 0)
    assert applied["status"] == "COMPLETED"

    replay = await service.plan(
        actor=_actor(), filename="master-tracker.csv", content=TRACKER_CSV, mapping=MAPPING
    )
    assert replay["counts"] == {"insert": 0, "update": 0, "skip": 2, "conflict": 0, "error": 0}
    assert len(list(await session.scalars(select(LicenseInventory)))) == 2


async def test_reconciliation_totals_match_the_imported_portfolio(
    session: AsyncSession, test_database_url: str
) -> None:
    settings = make_test_settings(test_database_url)
    await _seed_registry(session)
    service = TrackerImportService(session, settings)
    plan = await service.plan(
        actor=_actor(), filename="master-tracker.csv", content=TRACKER_CSV, mapping=MAPPING
    )
    await service.apply(uuid.UUID(str(plan["import_run_id"])), actor=_actor(), confirm=True)

    reconciliation = MigrationReconciliationService(session)
    totals = await reconciliation.totals()
    assert totals["legal_entities"] == 1
    assert totals["licenses_total"] == 2
    assert totals["licenses_active"] == 2
    assert totals["bonds_total"] == 0
    assert totals["cases_open"] == 0
    assert totals["obligations_overdue"] == 0

    matched = await reconciliation.reconcile({"legal_entities": 1, "licenses_active": 2})
    assert matched.matched is True

    mismatched = await reconciliation.reconcile({"licenses_active": 5})
    assert mismatched.matched is False
    assert mismatched.differences["licenses_active"] == {
        "expected": 5,
        "actual": 2,
        "delta": -3,
    }

    with pytest.raises(ValueError):
        await reconciliation.reconcile({"not_a_metric": 1})


async def test_reconciliation_counts_expiring_and_missing_renewal_dates(
    session: AsyncSession,
) -> None:
    await _seed_registry(session)
    entity = await session.scalar(select(LegalEntity))
    jurisdiction = await session.scalar(select(Jurisdiction))
    license_type = await session.scalar(select(LicenseType))
    assert entity and jurisdiction and license_type
    today = utcnow().date()

    session.add(
        LicenseInventory(
            license_key="expiring-soon",
            legal_entity_id=entity.id,
            jurisdiction_id=jurisdiction.id,
            license_type_id=license_type.id,
            filing_channel=FilingChannel.STATE_PORTAL.value,
            current_status=LicenseStatus.ACTIVE.value,
            source_confidence=SourceConfidence.TRACKER_IMPORT.value,
            expiration_date=today + timedelta(days=45),
        )
    )
    session.add(
        LicenseInventory(
            license_key="no-renewal-date",
            legal_entity_id=entity.id,
            jurisdiction_id=jurisdiction.id,
            license_type_id=license_type.id,
            filing_channel=FilingChannel.PAPER.value,
            current_status=LicenseStatus.ACTIVE.value,
            source_confidence=SourceConfidence.TRACKER_IMPORT.value,
            represents_additional_authority=True,
        )
    )
    await session.commit()

    totals = await MigrationReconciliationService(session).totals()
    assert totals["licenses_expiring_120_days"] == 1
    assert totals["licenses_missing_renewal_date"] == 1
    assert totals["licenses_without_owner"] == 2


# --------------------------------------------------- scheduler and heartbeat


async def test_scheduler_cycle_enqueues_durable_licensing_jobs(
    session_factory: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    settings = make_test_settings(test_database_url)
    ctx = WorkerContext.build(settings)
    try:
        counts = await run_scheduler_cycle(ctx)
    finally:
        await ctx.aclose()

    assert counts["licensing_jobs"] == 4
    assert "recovered_document_leases" in counts

    async with session_factory() as session:
        job_types = {job.job_type for job in (await session.scalars(select(LicensingJob))).all()}
        assert job_types == {
            "MATERIALIZE_DEADLINES",
            "CHECK_LICENSE_RENEWALS",
            "CHECK_INFORMATION_FRESHNESS",
            "CHECK_DOCUMENT_EXPIRY",
        }
        scheduler_beat = await session.scalar(
            select(WorkerHeartbeat).where(WorkerHeartbeat.worker_type == "scheduler")
        )
        assert scheduler_beat is not None


async def test_scheduler_cycle_is_idempotent_within_its_interval(
    session_factory: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    settings = make_test_settings(test_database_url)
    ctx = WorkerContext.build(settings)
    try:
        await run_scheduler_cycle(ctx)
        second = await run_scheduler_cycle(ctx)
    finally:
        await ctx.aclose()

    assert second["licensing_jobs"] == 0
    async with session_factory() as session:
        assert len(list(await session.scalars(select(LicensingJob)))) == 4


async def test_general_worker_reports_a_heartbeat_and_exits_when_idle(
    session_factory: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    settings: Settings = make_test_settings(
        test_database_url, GRAPH_WORKER_POLL_INTERVAL_SECONDS=0.01
    )
    args = argparse.Namespace(
        queues="graph,ingestion,classification,documents,communications,licensing",
        once=True,
        worker_id="milestone8-general-worker",
        poll_interval=0.01,
        max_jobs=None,
        log_level=None,
    )
    processed = await run_worker(settings, args)
    assert processed == 0

    async with session_factory() as session:
        beat = await session.scalar(
            select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == "milestone8-general-worker")
        )
        assert beat is not None
        assert beat.worker_type == "general-worker"
        assert (utcnow() - beat.last_heartbeat_at) < timedelta(minutes=1)
