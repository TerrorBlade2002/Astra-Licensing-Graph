"""Requirement-source registration, snapshotting, diffing, and review.

Governance rules enforced here:

* A changed source never alters an active rule. It creates a ``PENDING_REVIEW``
  snapshot and notifies the owner; a human decides whether rules are affected.
* Fetching is restricted to an explicit public-host allow-list. Authenticated
  portals are never fetched, and no CAPTCHA or access control is bypassed.
* A rule cannot be activated without at least one approved snapshot behind it.
"""

from __future__ import annotations

import difflib
import ipaddress
import socket
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.crypto import content_sha256
from app.core.exceptions import DomainError, NotFoundError, StateConflictError
from app.core.metrics import (
    REQUIREMENT_SOURCE_CHANGES_PENDING,
    REQUIREMENT_SOURCES_STALE,
)
from app.deadlines.alerts import source_change_alert, stale_source_alert
from app.evidence.base import EvidenceStore
from app.licensing.audit import add_licensing_audit, record_notification
from app.models import RequirementSource, RequirementSourceSnapshot
from app.models.mixins import utcnow
from app.requirements.freshness import assess_source
from app.requirements.taxonomy import (
    AuthorityLevel,
    SnapshotReviewStatus,
    SourceAccessMethod,
    SourceType,
    SourceVerificationStatus,
)


class SourceFetchNotAllowedError(DomainError):
    code = "source_fetch_not_allowed"
    http_status = 400


class RequirementSourceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register_source(
        self, *, actor: CurrentActor, commit: bool = True, **fields: Any
    ) -> RequirementSource:
        source_key = fields["source_key"]
        existing = await self.session.scalar(
            select(RequirementSource).where(RequirementSource.source_key == source_key)
        )
        if existing:
            raise StateConflictError(f"Source key {source_key!r} already exists.")
        url = fields.get("official_url")
        if url:
            self._assert_url_permitted(url, fetching=False)
        source = RequirementSource(
            source_key=source_key,
            source_type=fields["source_type"],
            authority_level=fields["authority_level"],
            title=fields["title"],
            jurisdiction_id=fields.get("jurisdiction_id"),
            organization_id=fields.get("organization_id"),
            official_url=url,
            access_method=fields.get("access_method")
            or SourceAccessMethod.MANUAL_URL_REGISTRATION.value,
            effective_date=fields.get("effective_date"),
            expiry_date=fields.get("expiry_date"),
            verification_status=SourceVerificationStatus.UNVERIFIED.value,
            owner_actor=fields.get("owner_actor") or actor.actor_id,
            freshness_days=fields.get("freshness_days"),
            citation_label=fields.get("citation_label"),
            notes=fields.get("notes"),
        )
        self.session.add(source)
        await self.session.flush()
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_source",
            entity_id=source.id,
            action="requirement_source_registered",
            after={"source_type": source.source_type, "authority": source.authority_level},
        )
        if commit:
            await self.session.commit()
        return source

    def _assert_url_permitted(self, url: str, *, fetching: bool) -> None:
        """Reject non-public and non-allow-listed hosts."""
        if not url.startswith("https://"):
            raise SourceFetchNotAllowedError("Source URLs must use HTTPS.")
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
        # Authenticated portals must never be fetched, registered URL or not.
        blocked_fragments = ("login", "signin", "auth", "account", "portal.secure")
        if any(fragment in url.lower() for fragment in blocked_fragments):
            raise SourceFetchNotAllowedError(
                "URLs that look like authenticated portal endpoints cannot be "
                "registered or fetched. Upload an exported document instead."
            )
        if not fetching:
            return
        if not self.settings.requirement_source_fetch_enabled:
            raise SourceFetchNotAllowedError(
                "Automated source fetching is disabled. Upload the document instead."
            )
        allowed = {h.strip().lower() for h in self.settings.requirement_source_allowed_hosts}
        if host not in allowed:
            raise SourceFetchNotAllowedError(
                f"Host {host!r} is not in REQUIREMENT_SOURCE_ALLOWED_HOSTS."
            )

    @staticmethod
    def _assert_public_resolution(url: str) -> None:
        """Block loopback, private, link-local, multicast, and reserved targets."""
        host = urlparse(url).hostname
        if not host:
            raise SourceFetchNotAllowedError("Source URL has no hostname.")
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise SourceFetchNotAllowedError(
                "Source hostname could not be resolved safely."
            ) from exc
        for raw in addresses:
            address = ipaddress.ip_address(raw)
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise SourceFetchNotAllowedError(
                    "Source hostname resolves to a non-public address."
                )

    async def fetch_public_snapshot(
        self,
        source_id: uuid.UUID,
        *,
        actor: CurrentActor,
        evidence_store: EvidenceStore,
    ) -> tuple[RequirementSourceSnapshot, bool]:
        """Fetch one allow-listed public source without authentication or redirects."""
        source = await self.session.get(RequirementSource, source_id)
        if source is None:
            raise NotFoundError("Requirement source not found.")
        if not source.official_url:
            raise StateConflictError("The requirement source has no official URL.")
        self._assert_url_permitted(source.official_url, fetching=True)
        self._assert_public_resolution(source.official_url)

        maximum = self.settings.requirement_source_max_bytes
        content = bytearray()
        timeout = httpx.Timeout(self.settings.requirement_source_fetch_timeout_seconds)
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                headers={"User-Agent": "Astra-Licensing-Source-Verifier/1.0"},
            ) as client,
            client.stream("GET", source.official_url) as response,
        ):
            if 300 <= response.status_code < 400:
                raise SourceFetchNotAllowedError(
                    "Source redirects are not followed automatically; review and "
                    "register the new official URL."
                )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > maximum:
                    raise StateConflictError(
                        "Requirement source exceeds REQUIREMENT_SOURCE_MAX_BYTES."
                    )

        raw = bytes(content)
        digest = content_sha256(raw)
        storage_key = f"requirement-sources/{source.id}/{digest}"
        stored = await evidence_store.put_bytes(
            storage_key,
            raw,
            content_type=content_type or "application/octet-stream",
        )
        extracted_text = (
            raw.decode("utf-8", errors="replace")
            if content_type in ("text/html", "text/plain", "application/json")
            else None
        )
        extracted_text_storage_uri = None
        if extracted_text is not None:
            extracted = await evidence_store.put_bytes(
                f"{storage_key}.extracted.txt",
                extracted_text.encode("utf-8"),
                content_type="text/plain",
            )
            extracted_text_storage_uri = extracted.storage_uri
        return await self.add_snapshot(
            source.id,
            actor=actor,
            content_sha256_value=digest,
            content_storage_uri=stored.storage_uri,
            extracted_text=extracted_text,
            extracted_text_storage_uri=extracted_text_storage_uri,
            change_summary="Allow-listed public source fetched for review.",
        )

    async def add_snapshot(
        self,
        source_id: uuid.UUID,
        *,
        actor: CurrentActor,
        content: bytes | None = None,
        content_sha256_value: str | None = None,
        content_storage_uri: str | None = None,
        extracted_text: str | None = None,
        extracted_text_storage_uri: str | None = None,
        effective_date: date | None = None,
        change_summary: str | None = None,
        commit: bool = True,
    ) -> tuple[RequirementSourceSnapshot, bool]:
        """Record a snapshot. Returns ``(snapshot, changed)``.

        An unchanged snapshot re-verifies the source without creating review work;
        a changed one always lands in ``PENDING_REVIEW``.
        """
        source = await self.session.get(RequirementSource, source_id)
        if source is None:
            raise NotFoundError("Requirement source not found.")

        digest = content_sha256_value or (content_sha256(content) if content is not None else None)
        if not digest:
            raise StateConflictError("A snapshot requires content or a content hash.")

        current = (
            await self.session.get(RequirementSourceSnapshot, source.current_snapshot_id)
            if source.current_snapshot_id
            else None
        )

        if current is not None and current.content_sha256 == digest:
            # No change: this is a verification event, not a new version.
            source.last_verified_at = utcnow()
            source.verification_status = SourceVerificationStatus.VERIFIED.value
            add_licensing_audit(
                self.session,
                actor=actor,
                entity_type="requirement_source",
                entity_id=source.id,
                action="requirement_source_verified_unchanged",
                after={"snapshot_version": current.version},
            )
            if commit:
                await self.session.commit()
            return current, False

        highest = (
            await self.session.scalar(
                select(func.max(RequirementSourceSnapshot.version)).where(
                    RequirementSourceSnapshot.requirement_source_id == source.id
                )
            )
            or 0
        )
        change_details: dict[str, Any] = {}
        if current is not None:
            change_details = {
                "previous_sha256": current.content_sha256,
                "new_sha256": digest,
                "previous_version": current.version,
            }
            if extracted_text and extracted_text_storage_uri and current.extracted_text_storage_uri:
                change_details["text_diff_available"] = True

        snapshot = RequirementSourceSnapshot(
            requirement_source_id=source.id,
            version=highest + 1,
            content_storage_uri=content_storage_uri,
            content_sha256=digest,
            extracted_text_storage_uri=extracted_text_storage_uri,
            retrieved_at=utcnow(),
            effective_date=effective_date,
            change_summary=change_summary
            or ("Initial snapshot." if current is None else "Source content changed."),
            change_details=change_details,
            previous_snapshot_id=current.id if current else None,
            # First snapshot of a source is still reviewed: an unreviewed
            # authority must not silently back a rule.
            review_status=SnapshotReviewStatus.PENDING_REVIEW.value,
        )
        self.session.add(snapshot)
        await self.session.flush()

        if current is not None:
            source.verification_status = SourceVerificationStatus.CHANGED_PENDING_REVIEW.value
        source.last_verified_at = utcnow()
        # current_snapshot_id only advances on approval, so active rules keep
        # citing the approved version until a reviewer accepts the change.

        if source.owner_actor:
            await record_notification(
                self.session,
                source_change_alert(
                    snapshot_id=snapshot.id,
                    source_id=source.id,
                    recipient_actor=source.owner_actor,
                    source_type=source.source_type,
                ),
            )
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_source_snapshot",
            entity_id=snapshot.id,
            action="requirement_source_snapshot_created",
            after={"version": snapshot.version, "review_status": snapshot.review_status},
        )
        if commit:
            await self.session.commit()
        return snapshot, True

    async def diff(self, snapshot_id: uuid.UUID) -> dict[str, Any]:
        """Structured comparison of a snapshot against its predecessor."""
        snapshot = await self.session.get(RequirementSourceSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError("Snapshot not found.")
        previous = (
            await self.session.get(RequirementSourceSnapshot, snapshot.previous_snapshot_id)
            if snapshot.previous_snapshot_id
            else None
        )
        return {
            "snapshot_id": str(snapshot.id),
            "version": snapshot.version,
            "review_status": snapshot.review_status,
            "content_sha256": snapshot.content_sha256,
            "previous": (
                {
                    "snapshot_id": str(previous.id),
                    "version": previous.version,
                    "content_sha256": previous.content_sha256,
                    "retrieved_at": previous.retrieved_at.isoformat(),
                }
                if previous
                else None
            ),
            "hash_changed": bool(previous and previous.content_sha256 != snapshot.content_sha256),
            "change_summary": snapshot.change_summary,
            "change_details": snapshot.change_details,
            "affects_rules": snapshot.affects_rules,
        }

    @staticmethod
    def text_diff(before: str, after: str, *, max_lines: int = 400) -> list[str]:
        """Unified diff of extracted text, for reviewer display."""
        lines = list(
            difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=2)
        )
        return lines[:max_lines]

    async def review_snapshot(
        self,
        snapshot_id: uuid.UUID,
        *,
        actor: CurrentActor,
        approve: bool,
        affects_rules: bool | None = None,
        notes: str | None = None,
        commit: bool = True,
    ) -> RequirementSourceSnapshot:
        """Approve or reject a pending snapshot.

        Approval advances the source's current snapshot pointer. It does **not**
        change any rule; a rule change requires a new rule-set version.
        """
        snapshot = await self.session.get(RequirementSourceSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError("Snapshot not found.")
        if snapshot.review_status != SnapshotReviewStatus.PENDING_REVIEW.value:
            raise StateConflictError(
                f"Snapshot is {snapshot.review_status}; only PENDING_REVIEW can be reviewed."
            )
        source = await self.session.get(RequirementSource, snapshot.requirement_source_id)
        if source is None:
            raise NotFoundError("Requirement source not found.")

        snapshot.reviewed_by_actor = actor.actor_id
        snapshot.reviewed_at = utcnow()
        snapshot.review_notes = (notes or None) if notes is None else notes[:2000]
        snapshot.affects_rules = affects_rules

        if approve:
            snapshot.review_status = SnapshotReviewStatus.APPROVED.value
            if source.current_snapshot_id and source.current_snapshot_id != snapshot.id:
                previous = await self.session.get(
                    RequirementSourceSnapshot, source.current_snapshot_id
                )
                if previous is not None:
                    previous.review_status = SnapshotReviewStatus.SUPERSEDED.value
            source.current_snapshot_id = snapshot.id
            source.verification_status = SourceVerificationStatus.VERIFIED.value
            source.last_verified_at = utcnow()
            if snapshot.effective_date:
                source.effective_date = snapshot.effective_date
        else:
            snapshot.review_status = SnapshotReviewStatus.REJECTED.value
            source.verification_status = (
                SourceVerificationStatus.VERIFIED.value
                if source.current_snapshot_id
                else SourceVerificationStatus.UNVERIFIED.value
            )

        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="requirement_source_snapshot",
            entity_id=snapshot.id,
            action="requirement_source_snapshot_reviewed",
            after={
                "review_status": snapshot.review_status,
                "affects_rules": affects_rules,
            },
        )
        if commit:
            await self.session.commit()
        return snapshot

    async def freshness_report(self, *, notify_owners: bool = False) -> list[dict[str, Any]]:
        """Assess every source's freshness, optionally notifying owners."""
        sources = list(await self.session.scalars(select(RequirementSource)))
        report: list[dict[str, Any]] = []
        stale = 0
        for source in sources:
            assessment = assess_source(
                source_type=source.source_type,
                authority_level=source.authority_level,
                last_verified_at=source.last_verified_at,
                override_days=source.freshness_days,
                default_days=self.settings.requirement_source_freshness_days,
            )
            if assessment.is_stale:
                stale += 1
                source.verification_status = SourceVerificationStatus.STALE.value
                if notify_owners and source.owner_actor:
                    await record_notification(
                        self.session,
                        stale_source_alert(
                            source_id=source.id,
                            recipient_actor=source.owner_actor,
                            source_type=source.source_type,
                            freshness_status=assessment.status,
                        ),
                    )
            report.append(
                {
                    "requirement_source_id": str(source.id),
                    "source_key": source.source_key,
                    "source_type": source.source_type,
                    "authority_level": source.authority_level,
                    "freshness_status": assessment.status,
                    "age_days": assessment.age_days,
                    "window_days": assessment.window_days,
                    "forces_counsel_review": assessment.forces_counsel_review,
                    "detail": assessment.detail,
                    "owner_actor": source.owner_actor,
                }
            )
        REQUIREMENT_SOURCES_STALE.set(stale)
        pending = (
            await self.session.scalar(
                select(func.count())
                .select_from(RequirementSourceSnapshot)
                .where(
                    RequirementSourceSnapshot.review_status
                    == SnapshotReviewStatus.PENDING_REVIEW.value
                )
            )
            or 0
        )
        REQUIREMENT_SOURCE_CHANGES_PENDING.set(pending)
        await self.session.commit()
        return report

    @staticmethod
    def is_authoritative(authority_level: str) -> bool:
        return authority_level in (
            AuthorityLevel.OFFICIAL_PRIMARY.value,
            AuthorityLevel.OFFICIAL_GUIDANCE.value,
            AuthorityLevel.APPROVED_COUNSEL.value,
        )

    @staticmethod
    def nmls_checklist_types() -> tuple[str, ...]:
        """NMLS provides separate new-application and renewal checklist exports."""
        return (
            SourceType.NMLS_CHECKLIST.value,
            SourceType.NMLS_RENEWAL_CHECKLIST.value,
        )
