"""Scheduler-cycle, runner-policy, and CLI coverage tests."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.graph.errors import (
    DeltaUrlValidationError,
    GraphApiError,
    GraphAuthError,
    GraphResponseInvalidError,
)
from app.jobs.enums import JobStatus, JobType
from app.models import GraphJob, MailboxSyncState, WorkerHeartbeat
from app.models.mixins import utcnow
from app.workers.context import WorkerContext
from app.workers.runner import classify_failure, resolve_job_types
from app.workers.scheduling import run_scheduler_cycle
from tests.conftest import (
    FakeTokenProvider,
    create_inbox_folder,
    create_mailbox,
    create_subscription_row,
)


def test_classify_failure_policy() -> None:
    code, _, retryable = classify_failure(GraphApiError(status_code=503))
    assert retryable and code == "http_503"
    code, _, retryable = classify_failure(GraphApiError(status_code=403))
    assert not retryable
    code, _, retryable = classify_failure(GraphAuthError("denied", error_code="persistent_401"))
    assert not retryable and code == "persistent_401"
    _, _, retryable = classify_failure(GraphResponseInvalidError("bad shape"))
    assert not retryable
    _, _, retryable = classify_failure(DeltaUrlValidationError("bad url"))
    assert not retryable
    _, _, retryable = classify_failure(DomainError("Folder sync lease is held elsewhere."))
    assert retryable
    _, _, retryable = classify_failure(OSError("disk broke"))
    assert retryable
    _, _, retryable = classify_failure(ValueError("bug"))
    assert not retryable


def test_resolve_job_types() -> None:
    assert resolve_job_types("sync") == [JobType.SYNC_FOLDER]
    assert JobType.ENSURE_SUBSCRIPTION in resolve_job_types("subscriptions,ingestion")
    with pytest.raises(SystemExit):
        resolve_job_types("bogus")


async def test_scheduler_cycle_enqueues_maintenance_and_recovers_leases(
    session: AsyncSession, graph_settings: Settings, test_database_url: str
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    # Subscription expiring inside the renewal window.
    row = await create_subscription_row(session, mailbox, folder)
    row.expiration_at = utcnow() + timedelta(minutes=5)
    # A stale sync state due for reconciliation.
    import uuid as uuid_mod

    session.add(MailboxSyncState(id=uuid_mod.uuid4(), mailbox_id=mailbox.id, folder_id=folder.id))
    # An abandoned RUNNING job with an expired lease.
    session.add(
        GraphJob(
            id=uuid_mod.uuid4(),
            job_type=JobType.INGEST_EMAIL.value,
            mailbox_id=mailbox.id,
            status=JobStatus.RUNNING.value,
            idempotency_key="expired-lease-job",
            max_attempts=3,
            available_at=utcnow(),
            lease_owner="dead-worker",
            lease_expires_at=utcnow() - timedelta(seconds=30),
        )
    )
    await session.commit()

    ctx = WorkerContext.build(
        graph_settings, worker_id="sched-test", token_provider=FakeTokenProvider()
    )
    try:
        counts = await run_scheduler_cycle(ctx)
    finally:
        await ctx.aclose()

    assert counts["subscription_jobs"] == 1
    assert counts["sync_jobs"] == 1
    assert counts["recovered_leases"] == 1

    session.expire_all()
    hb = await session.scalar(
        select(WorkerHeartbeat).where(WorkerHeartbeat.worker_type == "scheduler")
    )
    assert hb is not None

    ensure = await session.scalar(
        select(GraphJob).where(GraphJob.job_type == JobType.ENSURE_SUBSCRIPTION.value)
    )
    assert ensure is not None and "SCHEDULED_MAINTENANCE" in (ensure.reason or "")


def _cli_env(monkeypatch: pytest.MonkeyPatch, test_database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()


async def test_cli_graph_sync_enqueue_and_status(
    session: AsyncSession,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mailbox = await create_mailbox(session)
    await create_inbox_folder(session, mailbox)
    await session.commit()
    _cli_env(monkeypatch, test_database_url)
    try:
        import argparse

        from app.cli import graph_sync as cli

        args = argparse.Namespace(
            command="enqueue", mailbox=mailbox.address, folder="Inbox", reason="MANUAL"
        )
        assert await cli.run(args) == 0
        enqueue_out = json.loads(capsys.readouterr().out)
        assert enqueue_out["created"] is True

        args = argparse.Namespace(command="status", mailbox=mailbox.address, folder="Inbox")
        assert await cli.run(args) == 0
        status_out = json.loads(capsys.readouterr().out)
        assert status_out == {"status": "no_sync_state"}
    finally:
        get_settings.cache_clear()


async def test_cli_subscriptions_list(
    session: AsyncSession,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mailbox = await create_mailbox(session)
    folder = await create_inbox_folder(session, mailbox)
    await create_subscription_row(session, mailbox, folder)
    await session.commit()
    _cli_env(monkeypatch, test_database_url)
    try:
        import argparse

        from app.cli import graph_subscriptions as cli

        args = argparse.Namespace(command="list")
        assert await cli.run(args) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 1
        assert rows[0]["graph_subscription_id"] == "synth-sub-001"
        assert "client_state_hash" not in rows[0]
    finally:
        get_settings.cache_clear()


async def test_cli_diagnostics_config_is_secret_free(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "super-secret-value")
    get_settings.cache_clear()
    try:
        import argparse

        from app.cli import graph_diagnostics as cli

        args = argparse.Namespace(command="config")
        assert await cli.run(args) == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["graph_secret_configured"] is True
        assert "super-secret-value" not in out
        assert "astra_local_dev" not in out  # db password redacted
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_worker_runner_processes_one_job_via_cycle(
    session: AsyncSession, graph_settings: Settings
) -> None:
    """Exercise the runner claim/dispatch path with a mocked Graph."""
    import respx

    from app.jobs.service import GraphJobService
    from app.workers.runner import QUEUE_JOB_TYPES, WorkerRunner
    from tests.fixtures.graph_payloads import delta_link_url, delta_page

    mailbox = await create_mailbox(session)
    mailbox.graph_user_id = "synth-user"
    folder = await create_inbox_folder(session, mailbox)
    await session.commit()
    jobs = GraphJobService(session, graph_settings)
    await jobs.enqueue_sync_folder(mailbox_id=mailbox.id, folder_id=folder.id, reason="RUNNER_TEST")
    await session.commit()

    ctx = WorkerContext.build(
        graph_settings, worker_id="runner-test", token_provider=FakeTokenProvider()
    )
    try:
        with respx.mock:
            respx.get(
                "https://graph.microsoft.com/v1.0/users/synth-user/mailFolders/"
                "SYNTH-FOLDER-INBOX/messages/delta"
            ).mock(
                return_value=httpx.Response(
                    200, json=delta_page([], delta_link=delta_link_url("runner"))
                )
            )
            runner = WorkerRunner(
                ctx,
                job_types=[t for types in QUEUE_JOB_TYPES.values() for t in types],
                poll_interval=0.01,
                once=True,
            )
            processed = await runner.run()
    finally:
        await ctx.aclose()
    assert processed == 1
    session.expire_all()
    job = await session.scalar(select(GraphJob))
    assert job is not None and job.status == JobStatus.COMPLETED.value
