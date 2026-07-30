"""Isolated browser worker for reviewed portal-assistance jobs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.browser.security import assert_navigation_target
from app.browser.sessions import BrowserSessionRegistry, LiveBrowserSession
from app.core.config import Settings, get_settings
from app.core.exceptions import StateConflictError
from app.core.logging import configure_logging
from app.evidence.filesystem import FilesystemEvidenceStore
from app.models import (
    BrowserSession,
    DocumentVersion,
    HumanHandoff,
    PortalAdapterVersion,
    PortalDefinition,
    PortalJob,
    PortalRun,
    PortalRunDocument,
    UserPrincipal,
)
from app.models.mixins import utcnow
from app.portals.adapters.base import PortalAdapter
from app.portals.enums import (
    BrowserSessionStatus,
    HandoffStatus,
    HandoffType,
    PortalDocumentStatus,
    PortalJobType,
    PortalRunStatus,
)
from app.portals.registry import build_adapter
from app.repositories.portal_jobs import PortalJobRepository
from app.services.portal_entry_service import PortalEntryService
from app.services.portal_run_service import PortalRunService
from app.services.portal_session_service import PortalSessionService
from app.services.submission_evidence_service import SubmissionEvidenceService
from app.sharepoint.client import SharePointClient
from app.workers.context import WorkerContext
from app.workers.heartbeat import beat

logger = logging.getLogger(__name__)


class PortalBrowserWorker:
    def __init__(
        self,
        ctx: WorkerContext,
        *,
        once: bool = False,
        max_jobs: int | None = None,
    ) -> None:
        self.ctx = ctx
        self.once = once
        self.max_jobs = max_jobs
        self.processed = 0
        self.registry = BrowserSessionRegistry(ctx.settings)

    async def run(self) -> int:
        if not self.ctx.settings.browser_automation_enabled:
            logger.warning("Browser automation is disabled; portal worker is idle.")
            return 0
        while True:
            worked = await self.run_one_cycle()
            await self._expire_sessions()
            if self.once and not worked:
                return self.processed
            if self.max_jobs is not None and self.processed >= self.max_jobs:
                return self.processed
            if not worked:
                await asyncio.sleep(self.ctx.settings.portal_worker_poll_interval_seconds)

    async def run_one_cycle(self) -> bool:
        async with self.ctx.session_factory() as session:
            await beat(session, worker_id=self.ctx.worker_id, worker_type="portal-browser-worker")
            repo = PortalJobRepository(session)
            job = await repo.claim_next(
                worker_id=self.ctx.worker_id,
                lease_seconds=self.ctx.settings.portal_job_lease_seconds,
            )
            if job is None:
                return False
            try:
                waiting_human = await self._handle(session, job)
            except Exception as exc:
                await session.rollback()
                retryable = isinstance(
                    exc, (PlaywrightTimeoutError, PlaywrightError, OSError)
                ) and job.job_type not in {
                    PortalJobType.CAPTURE_SUBMISSION_RESULT.value,
                    PortalJobType.RECONCILE_SESSION.value,
                }
                await repo.record_failure(
                    job,
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:500],
                    retryable=retryable,
                )
                await self._fail_run_review(session, job, exc)
            else:
                if waiting_human:
                    await repo.mark_waiting_human(job)
                else:
                    await repo.mark_completed(job)
            self.processed += 1
            return True

    async def _handle(self, session: AsyncSession, job: PortalJob) -> bool:
        job_type = PortalJobType(job.job_type)
        if job_type is PortalJobType.START_BROWSER_SESSION:
            return await self._start_session(session, job)
        if job_type is PortalJobType.CLOSE_BROWSER_SESSION:
            await self._close_session(session, job)
            return False
        run, browser_session, live, adapter = await self._active_context(session, job)
        if job_type is PortalJobType.NAVIGATE_PORTAL:
            portal = await session.get(PortalDefinition, run.portal_definition_id)
            if portal is None:
                raise StateConflictError("Portal definition is missing.")
            target = job.payload.get("route", {}).get("url")
            if not isinstance(target, str):
                raise StateConflictError("Reviewed portal route has no URL.")
            assert_navigation_target(
                target,
                approved_hostname=portal.hostname,
                allow_local_test=self.ctx.settings.app_env == "test",
            )
            await adapter.navigate_to_filing(await self._page(live), job.payload.get("route", {}))
            await session.commit()
            return await self._reconcile(session, job, run, browser_session, live, adapter)
        if job_type is PortalJobType.ENTER_FIELDS:
            fields = await PortalEntryService(session, self.ctx.settings).resolve_fields_for_worker(
                run.id
            )
            page = await self._page(live)
            for field in fields:
                await adapter.enter_field(page, field.field_key, field.value)
                displayed = await adapter.read_field(page, field.field_key)
                await PortalEntryService(session, self.ctx.settings).record_worker_field_result(
                    field.run_field_id,
                    entered_value=field.value,
                    displayed_value=displayed,
                    worker_id=self.ctx.worker_id,
                )
            run.status = PortalRunStatus.VALIDATION_REQUIRED.value
            run.current_stage = run.status
            await session.commit()
            return False
        if job_type is PortalJobType.UPLOAD_DOCUMENTS:
            await self._upload_documents(session, run, live, adapter)
            run.status = PortalRunStatus.VALIDATION_REQUIRED.value
            run.current_stage = run.status
            await session.commit()
            return False
        if job_type is PortalJobType.RUN_PORTAL_VALIDATION:
            page = await self._page(live)
            validation_identity = await adapter.identify_current_page(page)
            if validation_identity is None:
                await self._unexpected_page(session, run, browser_session, adapter, page)
                return True
            messages = await adapter.list_validation_messages(page)
            await PortalRunService(session, self.ctx.settings).capture_validation(
                run.id,
                actor=self._system_actor(),
                messages=[
                    {**message, "blocking": True, "code": "PORTAL_VALIDATION"}
                    for message in messages
                ],
                observed_page_category=validation_identity.category,
            )
            return False
        if job_type is PortalJobType.CAPTURE_PRE_SUBMISSION:
            await PortalRunService(session, self.ctx.settings).create_snapshot(
                run.id, actor=self._system_actor()
            )
            return False
        if job_type is PortalJobType.RECONCILE_SESSION:
            return await self._reconcile(session, job, run, browser_session, live, adapter)
        if job_type is PortalJobType.CAPTURE_SUBMISSION_RESULT:
            # Reconciliation only. This path never invokes a click, form submit,
            # payment, or navigation action.
            page = await self._page(live)
            result = await adapter.detect_submission_result(page)
            if result.ambiguous:
                run.status = PortalRunStatus.SUBMISSION_RESULT_PENDING.value
                run.current_stage = run.status
                run.last_error_code = "ambiguous_submission_result"
                run.last_error_message = (
                    "Portal result is ambiguous. Reconcile evidence; never retry submission."
                )
                await session.commit()
                return True
            handoff_id = job.payload.get("handoff_id")
            handoff = (
                await session.get(HumanHandoff, uuid.UUID(str(handoff_id))) if handoff_id else None
            )
            if handoff is None or handoff.requested_from_user_id is None:
                raise StateConflictError("Submission capture lacks its human handoff.")
            principal = await session.get(UserPrincipal, handoff.requested_from_user_id)
            if principal is None:
                raise StateConflictError("Final-submit user principal is missing.")
            confirmation = (
                await adapter.capture_confirmation(page) if result.outcome == "CONFIRMED" else {}
            )
            human_actor = self._user_actor(
                principal, actor_id=str(job.payload.get("reported_by_actor", principal.id))
            )
            await SubmissionEvidenceService(session, self.ctx.settings).capture_submission_result(
                run.id,
                actor=human_actor,
                outcome=result.outcome,
                resulting_page_category=result.page_category,
                ambiguous=False,
                confirmation_number=(
                    str(confirmation.get("confirmation_reference"))[:300]
                    if confirmation.get("confirmation_reference")
                    else result.confirmation_reference
                ),
                filing_reference=None,
                evidence_document_id=None,
            )
            return False
        raise StateConflictError(f"Unsupported portal job type {job.job_type!r}.")

    async def _start_session(self, session: AsyncSession, job: PortalJob) -> bool:
        if job.portal_run_id is None:
            raise StateConflictError("Session-start job has no portal run.")
        run = await self._run(session, job.portal_run_id)
        portal, _review = await PortalRunService(session, self.ctx.settings).revalidate_governance(
            run
        )
        if run.assigned_operator_id is None:
            raise StateConflictError("Portal run has no assigned operator.")
        browser_session = (
            await session.get(BrowserSession, job.browser_session_id)
            if job.browser_session_id
            else None
        )
        if browser_session is None:
            now = utcnow()
            from datetime import timedelta

            browser_session = BrowserSession(
                portal_run_id=run.id,
                operator_user_id=run.assigned_operator_id,
                worker_id=self.ctx.worker_id,
                session_status=BrowserSessionStatus.STARTING.value,
                browser_type=self.ctx.settings.browser_type,
                ephemeral_profile_id=uuid.uuid4().hex,
                encrypted_session_reference=None,
                started_at=now,
                last_activity_at=now,
                expires_at=now + timedelta(minutes=self.ctx.settings.browser_session_max_minutes),
            )
            session.add(browser_session)
            await session.flush()
            job.browser_session_id = browser_session.id
        if browser_session.operator_user_id != run.assigned_operator_id:
            raise StateConflictError("Browser session belongs to another operator.")
        browser_session.worker_id = self.ctx.worker_id
        browser_session.session_status = BrowserSessionStatus.STARTING.value
        await session.commit()
        live = await self.registry.start(
            session_id=browser_session.id,
            operator_user_id=browser_session.operator_user_id,
            profile_id=browser_session.ephemeral_profile_id,
        )
        assert_navigation_target(
            portal.base_url,
            approved_hostname=portal.hostname,
            allow_local_test=self.ctx.settings.app_env == "test",
        )
        page = await live.context.new_page()
        await page.goto(portal.base_url, wait_until="domcontentloaded")
        adapter = await self._adapter(session, run)
        identity = await adapter.identify_current_page(page)
        if identity is None:
            await self._unexpected_page(session, run, browser_session, adapter, page)
            return True
        browser_session.session_status = BrowserSessionStatus.ACTIVE_AUTOMATION.value
        browser_session.last_activity_at = utcnow()
        run.status = PortalRunStatus.SESSION_ACTIVE.value
        run.current_stage = run.status
        await session.commit()
        login_state = await adapter.detect_login_state(page)
        if login_state == "LOGIN_REQUIRED":
            await PortalSessionService(session, self.ctx.settings).create_handoff(
                run.id,
                actor=None,
                handoff_type=HandoffType.LOGIN.value,
                requested_from_user_id=run.assigned_operator_id,
                browser_session_id=browser_session.id,
            )
            return True
        return False

    async def _reconcile(
        self,
        session: AsyncSession,
        job: PortalJob,
        run: PortalRun,
        browser_session: BrowserSession,
        live: LiveBrowserSession,
        adapter: PortalAdapter,
    ) -> bool:
        page = await self._page(live)
        identity = await adapter.identify_current_page(page)
        if identity is None:
            await self._unexpected_page(session, run, browser_session, adapter, page)
            return True
        handoff_id = job.payload.get("handoff_id")
        if handoff_id:
            handoff = await session.get(HumanHandoff, uuid.UUID(handoff_id))
            if handoff is None or handoff.portal_run_id != run.id:
                raise StateConflictError("Handoff reconciliation target is invalid.")
            expected = job.payload.get("expected_page_category")
            if expected and identity.category != expected:
                raise StateConflictError("Resulting portal page does not match human confirmation.")
            if identity.category in {
                "login",
                "terms",
                "mfa",
                "captcha",
                "attestation",
                "payment",
                "final_submit",
            } and identity.category == self._category_for_handoff(handoff.handoff_type):
                raise StateConflictError("Portal still shows the incomplete human-only step.")
            handoff.status = HandoffStatus.COMPLETED.value
            handoff.completed_at = utcnow()
            browser_session.session_status = BrowserSessionStatus.ACTIVE_AUTOMATION.value
            browser_session.last_activity_at = utcnow()
            run.status = PortalRunStatus.SESSION_ACTIVE.value
            run.current_stage = run.status
            await session.commit()
        next_type = self._handoff_for_category(identity.category)
        if next_type:
            if next_type == HandoffType.ATTESTATION.value:
                if run.assigned_signatory_id is None:
                    raise StateConflictError("Attestation page reached without assigned signatory.")
                attestation_fingerprint = await adapter.read_attestation_fingerprint(page)
                await SubmissionEvidenceService(session, self.ctx.settings).ensure_attestation(
                    run.id,
                    attestation_type="PORTAL_LEGAL_ATTESTATION",
                    required_actor_id=run.assigned_signatory_id,
                    text_fingerprint=attestation_fingerprint,
                    displayed_text_reference=(
                        "reviewed-portal-attestation-fingerprint"
                        if attestation_fingerprint
                        else None
                    ),
                )
            if next_type == HandoffType.PAYMENT.value:
                fee_summary = await adapter.read_payment_summary(page)
                await SubmissionEvidenceService(session, self.ctx.settings).ensure_payment(
                    run.id,
                    expected_fee_amount=None,
                    currency=None,
                    fee_summary={
                        "requires_human_review": True,
                        **fee_summary,
                    },
                )
            target = (
                run.assigned_signatory_id
                if next_type in {HandoffType.ATTESTATION.value, HandoffType.SIGNATURE.value}
                else run.assigned_payment_approver_id
                if next_type == HandoffType.PAYMENT.value
                else run.assigned_operator_id
            )
            await PortalSessionService(session, self.ctx.settings).create_handoff(
                run.id,
                actor=None,
                handoff_type=next_type,
                requested_from_user_id=target,
                browser_session_id=browser_session.id,
            )
            return True
        return False

    async def _upload_documents(
        self,
        session: AsyncSession,
        run: PortalRun,
        live: LiveBrowserSession,
        adapter: PortalAdapter,
    ) -> None:
        rows = list(
            await session.scalars(
                select(PortalRunDocument).where(
                    PortalRunDocument.portal_run_id == run.id,
                    PortalRunDocument.status.in_(
                        (
                            PortalDocumentStatus.UPLOAD_PENDING.value,
                            PortalDocumentStatus.FAILED_RETRYABLE.value,
                        )
                    ),
                )
            )
        )
        page = await self._page(live)
        for row in rows:
            version = await session.get(DocumentVersion, row.document_version_id)
            if version is None:
                raise StateConflictError("Pinned document version is missing.")
            temp_root = Path(
                tempfile.mkdtemp(
                    prefix="upload-",
                    dir=live.profile_path,
                )
            )
            local_store = FilesystemEvidenceStore(temp_root)
            try:
                result = await SharePointClient(
                    self.ctx.graph_client, self.ctx.settings
                ).download_to_store(
                    version.graph_drive_id,
                    version.graph_drive_item_id,
                    local_store,
                    "document",
                    max_bytes=self.ctx.settings.portal_upload_max_total_bytes,
                )
                if result.sha256_checksum.lower() != row.expected_sha256.lower():
                    raise StateConflictError(
                        "Pinned portal-upload document failed hash validation."
                    )
                local_path = temp_root / "document"
                row.status = PortalDocumentStatus.UPLOADING.value
                await adapter.upload_document(
                    page,
                    row.portal_document_category or "default",
                    str(local_path),
                )
                verified = await adapter.verify_uploaded_document(
                    page,
                    filename=row.expected_filename,
                    size_bytes=version.size_bytes,
                )
                if not verified:
                    row.status = PortalDocumentStatus.FAILED_REVIEW.value
                    row.discrepancy_details = {
                        "code": "DOCUMENT_VERSION_MISMATCH",
                        "blocking": True,
                    }
                    raise StateConflictError(
                        "Portal upload metadata did not match approved document."
                    )
                await PortalEntryService(session, self.ctx.settings).record_document_observation(
                    row.id,
                    actor_id=self.ctx.worker_id,
                    portal_display_name=row.expected_filename,
                    portal_size_bytes=version.size_bytes,
                    portal_upload_reference=None,
                )
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)

    async def _active_context(
        self, session: AsyncSession, job: PortalJob
    ) -> tuple[PortalRun, BrowserSession, LiveBrowserSession, PortalAdapter]:
        if job.portal_run_id is None or job.browser_session_id is None:
            raise StateConflictError("Portal browser job lacks run or session identity.")
        run = await self._run(session, job.portal_run_id)
        await PortalRunService(session, self.ctx.settings).revalidate_governance(run)
        browser_session = await session.get(BrowserSession, job.browser_session_id)
        if browser_session is None or browser_session.portal_run_id != run.id:
            raise StateConflictError("Browser session does not belong to the portal run.")
        if browser_session.expires_at <= utcnow():
            browser_session.session_status = BrowserSessionStatus.EXPIRED.value
            raise StateConflictError("Browser session expired.")
        live = self.registry.get(
            browser_session.id, operator_user_id=browser_session.operator_user_id
        )
        adapter = await self._adapter(session, run)
        return run, browser_session, live, adapter

    async def _adapter(self, session: AsyncSession, run: PortalRun) -> PortalAdapter:
        if run.portal_adapter_version_id is None:
            raise StateConflictError("Portal run has no pinned adapter.")
        version = await session.get(PortalAdapterVersion, run.portal_adapter_version_id)
        if version is None:
            raise StateConflictError("Pinned portal adapter is missing.")
        return build_adapter(
            version.adapter_key,
            locator_contract=version.locator_contract,
            contract_version=str(version.version),
        )

    async def _unexpected_page(
        self,
        session: AsyncSession,
        run: PortalRun,
        browser_session: BrowserSession,
        adapter: PortalAdapter,
        page: Page,
    ) -> None:
        diagnostic = await adapter.collect_page_contract(page)
        run.status = PortalRunStatus.FAILED_REVIEW.value
        run.current_stage = run.status
        run.last_error_code = "unexpected_portal_page"
        run.last_error_message = "Portal page did not match the reviewed adapter contract."
        await PortalSessionService(session, self.ctx.settings).create_handoff(
            run.id,
            actor=None,
            handoff_type=HandoffType.UNEXPECTED_PAGE.value,
            requested_from_user_id=run.assigned_operator_id,
            browser_session_id=browser_session.id,
        )
        logger.warning(
            "Portal adapter stopped on an unknown page",
            extra={
                "extra_fields": {
                    "portal_run_id": str(run.id),
                    "browser_session_id": str(browser_session.id),
                    "diagnostic_hash": diagnostic.get("sanitized_dom_sha256"),
                }
            },
        )

    async def _close_session(self, session: AsyncSession, job: PortalJob) -> None:
        if job.browser_session_id is None:
            return
        browser_session = await session.get(BrowserSession, job.browser_session_id)
        await self.registry.close(job.browser_session_id)
        if browser_session:
            browser_session.session_status = BrowserSessionStatus.CLOSED.value
            browser_session.closed_at = utcnow()
            browser_session.close_reason = str(job.payload.get("reason", "Closed"))[:500]
            browser_session.encrypted_session_reference = None
            await session.commit()

    async def _expire_sessions(self) -> None:
        async with self.ctx.session_factory() as session:
            rows = list(
                await session.scalars(
                    select(BrowserSession).where(
                        BrowserSession.worker_id == self.ctx.worker_id,
                        BrowserSession.session_status.in_(
                            (
                                BrowserSessionStatus.ACTIVE_AUTOMATION.value,
                                BrowserSessionStatus.ACTIVE_HUMAN_CONTROL.value,
                                BrowserSessionStatus.PAUSED.value,
                            )
                        ),
                    )
                )
            )
            for row in rows:
                inactive_seconds = (utcnow() - row.last_activity_at).total_seconds()
                if (
                    row.expires_at <= utcnow()
                    or inactive_seconds >= self.ctx.settings.browser_inactivity_timeout_minutes * 60
                ):
                    await self.registry.close(row.id)
                    row.session_status = BrowserSessionStatus.EXPIRED.value
                    row.closed_at = utcnow()
                    row.close_reason = "Session lifetime or inactivity timeout expired."
                    row.encrypted_session_reference = None
                    run = await session.get(PortalRun, row.portal_run_id)
                    if run and run.status != PortalRunStatus.SUBMITTED.value:
                        run.status = PortalRunStatus.BLOCKED.value
                        run.current_stage = run.status
                        run.last_error_code = "browser_session_expired"
            await session.commit()

    async def _fail_run_review(self, session: AsyncSession, job: PortalJob, exc: Exception) -> None:
        if job.portal_run_id is None:
            return
        run = await session.get(PortalRun, job.portal_run_id)
        if run is None:
            return
        if isinstance(exc, StateConflictError):
            run.status = PortalRunStatus.FAILED_REVIEW.value
            run.current_stage = run.status
            run.last_error_code = exc.code
            run.last_error_message = exc.message[:500]
            await session.commit()

    @staticmethod
    async def _page(live: LiveBrowserSession) -> Page:
        if live.context.pages:
            return live.context.pages[-1]
        return await live.context.new_page()

    @staticmethod
    def _handoff_for_category(category: str) -> str | None:
        return {
            "login": HandoffType.LOGIN.value,
            "terms": HandoffType.TERMS_ACCEPTANCE.value,
            "mfa": HandoffType.MFA.value,
            "captcha": HandoffType.CAPTCHA.value,
            "attestation": HandoffType.ATTESTATION.value,
            "signature": HandoffType.SIGNATURE.value,
            "payment": HandoffType.PAYMENT.value,
            "final_submit": HandoffType.FINAL_SUBMIT.value,
        }.get(category)

    @staticmethod
    def _category_for_handoff(handoff_type: str) -> str | None:
        return {
            HandoffType.LOGIN.value: "login",
            HandoffType.TERMS_ACCEPTANCE.value: "terms",
            HandoffType.MFA.value: "mfa",
            HandoffType.CAPTCHA.value: "captcha",
            HandoffType.ATTESTATION.value: "attestation",
            HandoffType.SIGNATURE.value: "signature",
            HandoffType.PAYMENT.value: "payment",
            HandoffType.FINAL_SUBMIT.value: "final_submit",
        }.get(handoff_type)

    @staticmethod
    def _system_actor() -> CurrentActor:
        from app.domain.enums import ActorType

        return CurrentActor(
            actor_type=ActorType.SYSTEM,
            actor_id="portal-browser-worker",
            tenant_id="system",
            object_id="portal-browser-worker",
            roles=(),
            scopes=(),
        )

    @staticmethod
    def _user_actor(principal: UserPrincipal, *, actor_id: str) -> CurrentActor:
        from app.domain.enums import ActorType

        return CurrentActor(
            actor_type=ActorType.HUMAN,
            actor_id=actor_id,
            tenant_id=principal.tenant_id,
            object_id=principal.object_id,
            display_name=principal.display_name,
            principal_name=principal.user_principal_name,
            roles=(),
            scopes=(),
        )

    @staticmethod
    async def _run(session: AsyncSession, run_id: uuid.UUID) -> PortalRun:
        run = await session.get(PortalRun, run_id)
        if run is None:
            raise StateConflictError("Portal run not found.")
        return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated portal browser worker.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--log-level", default=None)
    return parser


async def _run(settings: Settings, args: argparse.Namespace) -> int:
    ctx = WorkerContext.build(settings, worker_id=args.worker_id)
    try:
        return await PortalBrowserWorker(ctx, once=args.once, max_jobs=args.max_jobs).run()
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(args.log_level or settings.log_level, settings.log_format, settings.app_env)
    return asyncio.run(_run(settings, args))


if __name__ == "__main__":
    sys.exit(main())
