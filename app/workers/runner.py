"""Durable job worker.

Usage:
    python -m app.workers.runner --queues subscriptions,sync,ingestion
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging
from app.graph.errors import (
    DeltaUrlValidationError,
    GraphApiError,
    GraphAuthError,
    GraphResponseInvalidError,
)
from app.jobs.enums import JobType
from app.jobs.repository import GraphJobRepository
from app.jobs.service import GraphJobService
from app.models import GraphJob
from app.workers import classification_jobs, email_ingestion, graph_sync, subscription_maintenance
from app.workers.communication_jobs import CommunicationWorkerRunner
from app.workers.context import WorkerContext
from app.workers.document_jobs import (
    DOCUMENT_QUEUE_TYPES,
    DocumentWorkerRunner,
    resolve_document_job_types,
)
from app.workers.heartbeat import beat

logger = logging.getLogger(__name__)

QUEUE_JOB_TYPES: dict[str, list[JobType]] = {
    "subscriptions": [
        JobType.ENSURE_SUBSCRIPTION,
        JobType.RENEW_SUBSCRIPTION,
        JobType.RECREATE_SUBSCRIPTION,
    ],
    "sync": [JobType.SYNC_FOLDER],
    "ingestion": [JobType.INGEST_EMAIL],
    "classification": [JobType.CLASSIFY_EMAIL],
}

_HANDLERS = {
    JobType.SYNC_FOLDER.value: graph_sync.handle_sync_folder,
    JobType.INGEST_EMAIL.value: email_ingestion.handle_ingest_email,
    JobType.ENSURE_SUBSCRIPTION.value: subscription_maintenance.handle_subscription_job,
    JobType.RENEW_SUBSCRIPTION.value: subscription_maintenance.handle_subscription_job,
    JobType.RECREATE_SUBSCRIPTION.value: subscription_maintenance.handle_subscription_job,
    JobType.CLASSIFY_EMAIL.value: classification_jobs.handle_classification_job,
}


def classify_failure(exc: Exception) -> tuple[str, str, bool]:
    """Return (error_code, error_message, retryable)."""
    if isinstance(exc, GraphAuthError):
        return exc.error_code or "graph_auth_error", exc.message, False
    if isinstance(exc, GraphApiError):
        return (
            exc.graph_error_code or f"http_{exc.status_code}",
            exc.safe_message,
            exc.is_retryable or exc.status_code == 0,
        )
    if isinstance(exc, GraphResponseInvalidError | DeltaUrlValidationError):
        return exc.code, exc.message, False
    if isinstance(exc, DomainError):
        # Lease contention and similar transient coordination issues retry.
        retryable = exc.code in ("domain_error",) and "lease" in exc.message.lower()
        return exc.code, exc.message, retryable
    if isinstance(exc, OSError):
        return "storage_or_network_error", str(exc)[:200], True
    return type(exc).__name__, str(exc)[:200], False


class WorkerRunner:
    def __init__(
        self,
        ctx: WorkerContext,
        *,
        job_types: list[JobType],
        poll_interval: float,
        once: bool = False,
        max_jobs: int | None = None,
    ) -> None:
        self.ctx = ctx
        self.job_types = job_types
        self.poll_interval = poll_interval
        self.once = once
        self.max_jobs = max_jobs
        self.processed = 0

    async def run(self) -> int:
        while True:
            worked = await self.run_one_cycle()
            if self.once and not worked:
                return self.processed
            if self.max_jobs is not None and self.processed >= self.max_jobs:
                return self.processed
            if not worked:
                await asyncio.sleep(self.poll_interval)

    async def run_one_cycle(self) -> bool:
        """Claim and process at most one job. Returns True when work was done."""
        async with self.ctx.session_factory() as session:
            await beat(session, worker_id=self.ctx.worker_id, worker_type="graph-worker")
            repo = GraphJobRepository(session)
            job = await repo.claim_next(
                worker_id=self.ctx.worker_id,
                lease_seconds=self.ctx.settings.graph_job_lease_seconds,
                job_types=self.job_types,
            )
            if job is None:
                return False
            await self._process(session, job)
            self.processed += 1
            return True

    async def _process(self, session: AsyncSession, job: GraphJob) -> None:
        handler = _HANDLERS[job.job_type]
        logger.info(
            "Job claimed",
            extra={
                "extra_fields": {
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "attempt": job.attempts,
                }
            },
        )
        lease_task = asyncio.create_task(self._extend_lease_loop(job))
        try:
            await handler(self.ctx, session, job)
        except Exception as exc:
            lease_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lease_task
            await session.rollback()
            error_code, error_message, retryable = classify_failure(exc)
            logger.warning(
                "Job failed",
                extra={
                    "extra_fields": {
                        "job_id": str(job.id),
                        "job_type": job.job_type,
                        "error_code": error_code,
                        "retryable": retryable,
                        "attempt": job.attempts,
                    }
                },
            )
            service = GraphJobService(session, self.ctx.settings)
            await service.record_failure(
                job, error_code=error_code, error_message=error_message, retryable=retryable
            )
            return
        lease_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lease_task
        repo = GraphJobRepository(session)
        await repo.mark_completed(job)
        logger.info(
            "Job completed",
            extra={"extra_fields": {"job_id": str(job.id), "job_type": job.job_type}},
        )

    async def _extend_lease_loop(self, job: GraphJob) -> None:
        interval = self.ctx.settings.graph_job_heartbeat_interval_seconds
        while True:
            await asyncio.sleep(interval)
            async with self.ctx.session_factory() as session:
                repo = GraphJobRepository(session)
                extended = await repo.extend_lease(
                    job.id,
                    worker_id=self.ctx.worker_id,
                    lease_seconds=self.ctx.settings.graph_job_lease_seconds,
                )
                if not extended:
                    logger.warning(
                        "Lease extension failed; job may have been recovered",
                        extra={"extra_fields": {"job_id": str(job.id)}},
                    )
                    return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable Graph job worker.")
    parser.add_argument("--queues", default="subscriptions,sync,ingestion")
    parser.add_argument("--once", action="store_true", help="Drain and exit when idle.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--log-level", default=None)
    return parser


def resolve_job_types(queues: str) -> list[JobType]:
    job_types: list[JobType] = []
    for queue in queues.split(","):
        name = queue.strip().lower()
        if not name:
            continue
        if name not in QUEUE_JOB_TYPES:
            raise SystemExit(f"Unknown queue: {name!r} (valid: {sorted(QUEUE_JOB_TYPES)})")
        job_types.extend(QUEUE_JOB_TYPES[name])
    return job_types or [t for types in QUEUE_JOB_TYPES.values() for t in types]


async def run_worker(settings: Settings, args: argparse.Namespace) -> int:
    ctx = WorkerContext.build(settings, worker_id=args.worker_id)
    try:
        queue_names = {value.strip().lower() for value in args.queues.split(",") if value.strip()}
        communication_names = {"communications", "drafts", "send", "moves"}
        if queue_names & communication_names:
            if queue_names - communication_names:
                raise SystemExit("Communication queues must run in a separate worker process.")
            return await CommunicationWorkerRunner(
                ctx, once=args.once, max_jobs=args.max_jobs
            ).run()
        document_names = set(DOCUMENT_QUEUE_TYPES)
        if queue_names & document_names:
            if queue_names - document_names:
                raise SystemExit("Graph and document queues must run in separate worker processes.")
            return await DocumentWorkerRunner(
                ctx,
                job_types=resolve_document_job_types(args.queues),
                once=args.once,
                max_jobs=args.max_jobs,
            ).run()
        runner = WorkerRunner(
            ctx,
            job_types=resolve_job_types(args.queues),
            poll_interval=args.poll_interval or settings.graph_worker_poll_interval_seconds,
            once=args.once,
            max_jobs=args.max_jobs,
        )
        return await runner.run()
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(args.log_level or settings.log_level, settings.log_format, settings.app_env)
    processed = asyncio.run(run_worker(settings, args))
    logger.info("Worker exiting", extra={"extra_fields": {"jobs_processed": processed}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
