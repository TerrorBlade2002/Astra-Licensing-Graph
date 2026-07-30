"""Durable job worker.

Usage:
    python -m app.workers.runner --queues subscriptions,sync,ingestion
    python -m app.workers.runner --queues graph,ingestion,classification,\
documents,communications,licensing

Each queue belongs to a family with its own claim loop. A single process may
run several families at once — the deployed general worker does exactly that —
in which case one loop per family runs concurrently on the same event loop and
database engine.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from typing import Protocol

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
from app.licensing.jobs import LICENSING_QUEUE_TYPES, resolve_licensing_job_types
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
from app.workers.licensing_jobs import LicensingWorkerRunner

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

#: Operator-facing shorthand. "graph" is how the mailbox subscription and
#: delta-sync queues are named in the deployment documentation.
QUEUE_ALIASES: dict[str, tuple[str, ...]] = {
    "graph": ("subscriptions", "sync"),
}

COMMUNICATION_QUEUES = frozenset({"communications", "drafts", "send", "moves"})
PORTAL_QUEUES = frozenset({"portals"})

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
            # Liveness is reported by the process-level heartbeat in
            # ``run_worker`` so that an idle or multi-family worker still
            # appears alive to the operations status endpoint.
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
    parser = argparse.ArgumentParser(description="Durable job worker.")
    parser.add_argument(
        "--queues",
        default="subscriptions,sync,ingestion",
        help=f"Comma-separated queues. Valid names: {', '.join(all_queue_names())}.",
    )
    parser.add_argument("--once", action="store_true", help="Drain and exit when idle.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--log-level", default=None)
    return parser


def resolve_job_types(queues: str) -> list[JobType]:
    job_types: list[JobType] = []
    for name in expand_queue_names(queues):
        if name not in QUEUE_JOB_TYPES:
            raise SystemExit(f"Unknown queue: {name!r} (valid: {sorted(QUEUE_JOB_TYPES)})")
        job_types.extend(QUEUE_JOB_TYPES[name])
    return job_types or [t for types in QUEUE_JOB_TYPES.values() for t in types]


def expand_queue_names(queues: str) -> list[str]:
    """Normalize a comma-separated queue list, expanding operator shorthand."""
    names: list[str] = []
    for value in queues.split(","):
        name = value.strip().lower()
        if not name:
            continue
        for expanded in QUEUE_ALIASES.get(name, (name,)):
            if expanded not in names:
                names.append(expanded)
    return names


def all_queue_names() -> list[str]:
    return sorted(
        set(QUEUE_JOB_TYPES)
        | COMMUNICATION_QUEUES
        | set(DOCUMENT_QUEUE_TYPES)
        | set(LICENSING_QUEUE_TYPES)
        | PORTAL_QUEUES
        | set(QUEUE_ALIASES)
    )


def partition_queues(queues: str) -> dict[str, list[str]]:
    """Group requested queues by the worker family that serves them."""
    families: dict[str, list[str]] = {}
    for name in expand_queue_names(queues):
        if name in QUEUE_JOB_TYPES:
            family = "graph"
        elif name in COMMUNICATION_QUEUES:
            family = "communications"
        elif name in DOCUMENT_QUEUE_TYPES:
            family = "documents"
        elif name in LICENSING_QUEUE_TYPES:
            family = "licensing"
        elif name in PORTAL_QUEUES:
            family = "portals"
        else:
            raise SystemExit(f"Unknown queue: {name!r} (valid: {all_queue_names()})")
        families.setdefault(family, []).append(name)
    return families


_WORKER_TYPES = {
    "graph": "graph-worker",
    "communications": "communication-worker",
    "documents": "document-worker",
    "licensing": "licensing-worker",
    "portals": "portal-browser-worker",
}


async def _heartbeat_loop(ctx: WorkerContext, worker_type: str) -> None:
    """Report liveness even while every queue is idle."""
    interval = max(5, ctx.settings.graph_job_heartbeat_interval_seconds)
    while True:
        try:
            async with ctx.session_factory() as session:
                await beat(session, worker_id=ctx.worker_id, worker_type=worker_type)
        except Exception:
            logger.warning("Worker heartbeat write failed", exc_info=True)
        await asyncio.sleep(interval)


class QueueRunner(Protocol):
    """Every worker family exposes the same claim-loop entry point."""

    async def run(self) -> int: ...


def _build_family_runner(
    family: str, queues: list[str], ctx: WorkerContext, args: argparse.Namespace
) -> QueueRunner:
    joined = ",".join(queues)
    settings = ctx.settings
    if family == "communications":
        return CommunicationWorkerRunner(ctx, once=args.once, max_jobs=args.max_jobs)
    if family == "documents":
        return DocumentWorkerRunner(
            ctx,
            job_types=resolve_document_job_types(joined),
            once=args.once,
            max_jobs=args.max_jobs,
        )
    if family == "licensing":
        return LicensingWorkerRunner(
            ctx,
            job_types=resolve_licensing_job_types(joined),
            once=args.once,
            max_jobs=args.max_jobs,
        )
    if family == "portals":
        # Imported lazily: only the browser-worker image ships Chromium.
        from app.workers.portal_jobs import PortalBrowserWorker

        return PortalBrowserWorker(ctx, once=args.once, max_jobs=args.max_jobs)
    return WorkerRunner(
        ctx,
        job_types=resolve_job_types(joined),
        poll_interval=args.poll_interval or settings.graph_worker_poll_interval_seconds,
        once=args.once,
        max_jobs=args.max_jobs,
    )


async def run_worker(settings: Settings, args: argparse.Namespace) -> int:
    ctx = WorkerContext.build(settings, worker_id=args.worker_id)
    families = partition_queues(args.queues) or {"graph": list(QUEUE_JOB_TYPES)}
    worker_type = _WORKER_TYPES[next(iter(families))] if len(families) == 1 else "general-worker"
    logger.info(
        "Worker starting",
        extra={"extra_fields": {"worker_id": ctx.worker_id, "families": sorted(families)}},
    )
    heartbeat = asyncio.create_task(_heartbeat_loop(ctx, worker_type))
    try:
        runners = [
            _build_family_runner(family, queues, ctx, args) for family, queues in families.items()
        ]
        results = await asyncio.gather(*(runner.run() for runner in runners))
        return sum(int(result or 0) for result in results)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
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
