"""Master-tracker import: plan, review, apply, and verify.

Row-level transactional safety: each row is applied inside a SAVEPOINT, so one bad
row is recorded as an error without corrupting the rest of the run.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.core.config import Settings
from app.core.crypto import content_sha256
from app.core.exceptions import NotFoundError, StateConflictError
from app.core.metrics import TRACKER_IMPORT_ERRORS_TOTAL, TRACKER_IMPORT_ROWS_TOTAL
from app.imports.enums import (
    APPLYING_ROW_ACTIONS,
    ImportErrorCode,
    ImportRowAction,
    ImportRunStatus,
    TrackerColumn,
)
from app.imports.master_tracker import (
    NormalizedRow,
    detect_format,
    normalize_rows,
    preview,
    read_csv,
    read_xlsx,
    reject_unsafe_extension,
    validate_mapping,
)
from app.licensing.audit import add_licensing_audit
from app.licensing.enums import LicenseStatus, SourceConfidence
from app.models import (
    Jurisdiction,
    LegalEntity,
    LicenseInventory,
    LicenseType,
    TrackerImportRow,
    TrackerImportRun,
)
from app.models.mixins import utcnow
from app.services.license_inventory_service import LicenseInventoryService


class TrackerImportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _check_upload(self, *, filename: str, content: bytes) -> None:
        if not self.settings.tracker_import_enabled:
            raise StateConflictError("Tracker import is disabled by configuration.")
        if len(content) > self.settings.tracker_import_max_bytes:
            raise StateConflictError("The file exceeds TRACKER_IMPORT_MAX_BYTES.")
        lowered = filename.lower()
        if not any(
            lowered.endswith(ext) for ext in self.settings.tracker_import_allowed_extensions
        ):
            raise StateConflictError(
                f"{filename!r} is not an allowed tracker file type "
                f"({self.settings.tracker_import_allowed_extensions})."
            )
        reject_unsafe_extension(filename)

    async def plan(
        self,
        *,
        actor: CurrentActor,
        filename: str,
        content: bytes,
        mapping: dict[str, str] | None = None,
        sheet_name: str | None = None,
        source_document_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Parse and dry-run a tracker file, persisting the plan for review."""
        self._check_upload(filename=filename, content=content)
        digest = content_sha256(content)
        sheet = preview(content, filename=filename, sheet_name=sheet_name)

        run = TrackerImportRun(
            source_filename=filename[:300],
            source_sha256=digest,
            status=ImportRunStatus.PLANNING.value,
            mapping_config={"mapping": mapping or {}, "sheet_name": sheet.selected_sheet},
            dry_run=True,
            sheet_name=sheet.selected_sheet,
            detected_headers=sheet.headers,
            source_document_id=source_document_id,
            initiated_by_actor=actor.actor_id,
            started_at=utcnow(),
        )
        self.session.add(run)
        await self.session.flush()

        if not mapping:
            # Header discovery pass: the Admin maps columns before any row work.
            run.status = ImportRunStatus.PLANNED.value
            run.completed_at = utcnow()
            if commit:
                await self.session.commit()
            return {
                "import_run_id": str(run.id),
                "status": run.status,
                "headers": sheet.headers,
                "sheet_names": sheet.sheet_names,
                "selected_sheet": sheet.selected_sheet,
                "sample_rows": sheet.sample_rows,
                "total_rows": sheet.total_rows,
                "formula_cell_count": sheet.formula_cell_count,
                "notes": sheet.notes,
                "mapping_required": True,
            }

        problems = validate_mapping(mapping, sheet.headers)
        if problems:
            run.status = ImportRunStatus.FAILED.value
            run.last_error_message = "; ".join(problems)[:1000]
            run.completed_at = utcnow()
            if commit:
                await self.session.commit()
            raise StateConflictError(
                "The column mapping is invalid.", details={"problems": problems}
            )

        normalized = await self._normalize(content, filename, mapping, sheet.selected_sheet)
        counts = {"insert": 0, "update": 0, "skip": 0, "conflict": 0, "error": 0}

        for row in normalized:
            action, target, issues = await self._decide(row)
            self.session.add(
                TrackerImportRow(
                    import_run_id=run.id,
                    row_number=row.row_number,
                    row_fingerprint=row.fingerprint,
                    source_data=row.source,
                    normalized_data=self._serialise(row.values),
                    action=action,
                    target_record_id=target,
                    error_details=issues or None,
                )
            )
            if action == ImportRowAction.INSERT.value:
                counts["insert"] += 1
            elif action == ImportRowAction.UPDATE.value:
                counts["update"] += 1
            elif action == ImportRowAction.ERROR.value:
                counts["error"] += 1
            elif action == ImportRowAction.CONFLICT_REVIEW.value:
                counts["conflict"] += 1
            else:
                counts["skip"] += 1
            TRACKER_IMPORT_ROWS_TOTAL.labels(action=action).inc()

        run.status = ImportRunStatus.PLANNED.value
        run.inserted_count = counts["insert"]
        run.updated_count = counts["update"]
        run.skipped_count = counts["skip"]
        run.error_count = counts["error"]
        run.conflict_count = counts["conflict"]
        run.completed_at = utcnow()
        TRACKER_IMPORT_ERRORS_TOTAL.inc(counts["error"])
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="tracker_import_run",
            entity_id=run.id,
            action="tracker_import_planned",
            after=counts,
        )
        if commit:
            await self.session.commit()
        return {
            "import_run_id": str(run.id),
            "status": run.status,
            "dry_run": True,
            "counts": counts,
            "total_rows": len(normalized),
            "formula_cell_count": sheet.formula_cell_count,
            "notes": sheet.notes,
            "mapping_required": False,
        }

    async def _normalize(
        self, content: bytes, filename: str, mapping: dict[str, str], sheet_name: str | None
    ) -> list[NormalizedRow]:
        if detect_format(filename) == "XLSX":
            _, rows, _, _ = read_xlsx(
                content, sheet_name=sheet_name, max_rows=self.settings.tracker_import_max_rows
            )
        else:
            _, rows, _ = read_csv(content, max_rows=self.settings.tracker_import_max_rows)
        return normalize_rows(rows, mapping)

    @staticmethod
    def _serialise(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in values.items()
        }

    @staticmethod
    def _restore_typed_values(values: dict[str, Any]) -> dict[str, Any]:
        """Restore ISO date strings persisted in JSONB to domain date values."""
        restored = dict(values)
        for key in (
            TrackerColumn.ISSUE_DATE.value,
            TrackerColumn.EFFECTIVE_DATE.value,
            TrackerColumn.EXPIRATION_DATE.value,
            TrackerColumn.RENEWAL_DUE_DATE.value,
        ):
            value = restored.get(key)
            if isinstance(value, str) and value:
                restored[key] = date.fromisoformat(value)
        return restored

    async def _resolve_scope(
        self, row: NormalizedRow
    ) -> tuple[LegalEntity | None, Jurisdiction | None, LicenseType | None, list[dict[str, Any]]]:
        """Resolve names to registry rows. Unresolved names are errors, not guesses."""
        issues: list[dict[str, Any]] = []
        entity_name = str(row.values.get(TrackerColumn.LEGAL_ENTITY.value) or "").strip()
        jurisdiction_name = str(row.values.get(TrackerColumn.JURISDICTION.value) or "").strip()
        type_name = str(row.values.get(TrackerColumn.LICENSE_TYPE.value) or "").strip()

        entity = await self.session.scalar(
            select(LegalEntity).where(func.lower(LegalEntity.legal_name) == entity_name.lower())
        ) or await self.session.scalar(
            select(LegalEntity).where(
                func.lower(LegalEntity.entity_key) == entity_name.lower().replace(" ", "-")
            )
        )
        if entity is None and entity_name:
            issues.append(
                {
                    "code": ImportErrorCode.UNRESOLVED_LEGAL_ENTITY.value,
                    "field": TrackerColumn.LEGAL_ENTITY.value,
                    "detail": f"No legal entity matches {entity_name!r}. Create it first.",
                }
            )
        jurisdiction = await self.session.scalar(
            select(Jurisdiction).where(func.lower(Jurisdiction.name) == jurisdiction_name.lower())
        ) or await self.session.scalar(
            select(Jurisdiction).where(
                func.lower(Jurisdiction.jurisdiction_key) == jurisdiction_name.lower()
            )
        )
        if jurisdiction is None and jurisdiction_name:
            issues.append(
                {
                    "code": ImportErrorCode.UNRESOLVED_JURISDICTION.value,
                    "field": TrackerColumn.JURISDICTION.value,
                    "detail": f"No jurisdiction matches {jurisdiction_name!r}.",
                }
            )
        license_type = await self.session.scalar(
            select(LicenseType).where(func.lower(LicenseType.name) == type_name.lower())
        ) or await self.session.scalar(
            select(LicenseType).where(
                func.lower(LicenseType.license_type_key) == type_name.lower().replace(" ", "-")
            )
        )
        if license_type is None and type_name:
            issues.append(
                {
                    "code": ImportErrorCode.UNRESOLVED_LICENSE_TYPE.value,
                    "field": TrackerColumn.LICENSE_TYPE.value,
                    "detail": f"No licence type matches {type_name!r}.",
                }
            )
        return entity, jurisdiction, license_type, issues

    async def _decide(
        self, row: NormalizedRow
    ) -> tuple[str, uuid.UUID | None, list[dict[str, Any]]]:
        """Classify one row into an action without mutating anything."""
        issues = [
            {"code": issue.code, "field": issue.column, "detail": issue.message}
            for issue in row.issues
        ]
        if issues:
            return ImportRowAction.ERROR.value, None, issues

        entity, jurisdiction, license_type, scope_issues = await self._resolve_scope(row)
        if scope_issues:
            return ImportRowAction.ERROR.value, None, scope_issues
        if entity is None or jurisdiction is None or license_type is None:
            return ImportRowAction.ERROR.value, None, issues

        number = row.values.get(TrackerColumn.LICENSE_NUMBER.value)
        stmt = select(LicenseInventory).where(
            LicenseInventory.legal_entity_id == entity.id,
            LicenseInventory.jurisdiction_id == jurisdiction.id,
            LicenseInventory.license_type_id == license_type.id,
        )
        if number:
            stmt = stmt.where(LicenseInventory.license_number == str(number))
        existing = list(await self.session.scalars(stmt))

        if not existing:
            return ImportRowAction.INSERT.value, None, []
        if len(existing) > 1:
            return (
                ImportRowAction.CONFLICT_REVIEW.value,
                existing[0].id,
                [
                    {
                        "code": ImportErrorCode.CONFLICTING_EXISTING_RECORD.value,
                        "detail": f"{len(existing)} inventory rows match this row's key.",
                    }
                ],
            )
        target = existing[0]

        # Never silently overwrite a record verified more recently than the tracker.
        if target.source_confidence in (
            SourceConfidence.VERIFIED_DOCUMENT.value,
            SourceConfidence.REGULATOR_CONFIRMED.value,
        ):
            incoming_expiry = row.values.get(TrackerColumn.EXPIRATION_DATE.value)
            if (
                incoming_expiry
                and target.expiration_date
                and incoming_expiry != target.expiration_date
            ):
                return (
                    ImportRowAction.CONFLICT_REVIEW.value,
                    target.id,
                    [
                        {
                            "code": ImportErrorCode.TARGET_MODIFIED_MORE_RECENTLY.value,
                            "detail": (
                                "The existing record is backed by verified evidence and "
                                "disagrees with the spreadsheet. Resolve manually."
                            ),
                        }
                    ],
                )

        if self._is_unchanged(target, row):
            return ImportRowAction.SKIP_UNCHANGED.value, target.id, []
        return ImportRowAction.UPDATE.value, target.id, []

    @staticmethod
    def _is_unchanged(target: LicenseInventory, row: NormalizedRow) -> bool:
        comparisons = (
            (TrackerColumn.STATUS.value, target.current_status),
            (TrackerColumn.FILING_CHANNEL.value, target.filing_channel),
            (TrackerColumn.EXPIRATION_DATE.value, target.expiration_date),
            (TrackerColumn.ISSUE_DATE.value, target.issue_date),
            (TrackerColumn.LICENSE_NUMBER.value, target.license_number),
        )
        for key, current in comparisons:
            incoming = row.values.get(key)
            if incoming is not None and incoming != current:
                return False
        return True

    async def apply(
        self, run_id: uuid.UUID, *, actor: CurrentActor, confirm: bool = False
    ) -> dict[str, Any]:
        """Apply a planned run. Requires explicit confirmation."""
        if not confirm:
            raise StateConflictError("Applying a tracker import requires explicit confirmation.")
        plan = await self.session.get(TrackerImportRun, run_id)
        if plan is None:
            raise NotFoundError("Import run not found.")
        if plan.status != ImportRunStatus.PLANNED.value:
            raise StateConflictError(f"A run in {plan.status} cannot be applied.")

        rows = list(
            await self.session.scalars(
                select(TrackerImportRow)
                .where(
                    TrackerImportRow.import_run_id == plan.id,
                    TrackerImportRow.action.in_(APPLYING_ROW_ACTIONS),
                )
                .order_by(TrackerImportRow.row_number)
            )
        )
        applied = TrackerImportRun(
            source_filename=plan.source_filename,
            source_sha256=plan.source_sha256,
            status=ImportRunStatus.APPLYING.value,
            mapping_config=plan.mapping_config,
            dry_run=False,
            sheet_name=plan.sheet_name,
            detected_headers=plan.detected_headers,
            source_document_id=plan.source_document_id,
            plan_run_id=plan.id,
            initiated_by_actor=actor.actor_id,
            started_at=utcnow(),
        )
        self.session.add(applied)
        await self.session.flush()

        inventory = LicenseInventoryService(self.session)
        inserted = updated = errors = 0

        for row in rows:
            values = self._restore_typed_values(dict(row.normalized_data or {}))
            try:
                # SAVEPOINT: a single failing row must not roll back the run.
                async with self.session.begin_nested():
                    entity = await self.session.scalar(
                        select(LegalEntity).where(
                            func.lower(LegalEntity.legal_name)
                            == str(values.get(TrackerColumn.LEGAL_ENTITY.value, "")).lower()
                        )
                    )
                    jurisdiction = await self.session.scalar(
                        select(Jurisdiction).where(
                            func.lower(Jurisdiction.name)
                            == str(values.get(TrackerColumn.JURISDICTION.value, "")).lower()
                        )
                    )
                    license_type = await self.session.scalar(
                        select(LicenseType).where(
                            func.lower(LicenseType.name)
                            == str(values.get(TrackerColumn.LICENSE_TYPE.value, "")).lower()
                        )
                    )
                    if entity is None or jurisdiction is None or license_type is None:
                        raise ValueError("Scope could not be resolved at apply time.")

                    payload = {
                        "license_number": values.get(TrackerColumn.LICENSE_NUMBER.value),
                        "nmls_license_id": values.get(TrackerColumn.NMLS_LICENSE_ID.value),
                        "filing_channel": values.get(TrackerColumn.FILING_CHANNEL.value),
                        "current_status": values.get(TrackerColumn.STATUS.value)
                        or LicenseStatus.UNKNOWN.value,
                        "issue_date": values.get(TrackerColumn.ISSUE_DATE.value),
                        "effective_date": values.get(TrackerColumn.EFFECTIVE_DATE.value),
                        "expiration_date": values.get(TrackerColumn.EXPIRATION_DATE.value),
                        "renewal_due_date": values.get(TrackerColumn.RENEWAL_DUE_DATE.value),
                        "responsible_owner": values.get(TrackerColumn.RESPONSIBLE_OWNER.value),
                        "notes": values.get(TrackerColumn.NOTES.value),
                        "source_confidence": SourceConfidence.TRACKER_IMPORT.value,
                        "source_document_id": plan.source_document_id,
                        "event_source_type": "TRACKER_IMPORT",
                        "event_source_reference": f"import_run:{applied.id}",
                    }
                    payload = {k: v for k, v in payload.items() if v is not None}

                    if row.action == ImportRowAction.INSERT.value:
                        record = await inventory.create_license(
                            actor=actor,
                            legal_entity_id=entity.id,
                            jurisdiction_id=jurisdiction.id,
                            license_type_id=license_type.id,
                            commit=False,
                            **payload,
                        )
                        row.target_record_id = record.id
                        inserted += 1
                    else:
                        if row.target_record_id is None:
                            raise ValueError("Update row has no target record.")
                        status = payload.pop("current_status", None)
                        payload.pop("event_source_type", None)
                        payload.pop("event_source_reference", None)
                        await inventory.update_license(
                            row.target_record_id, actor=actor, commit=False, **payload
                        )
                        target = await self.session.get(LicenseInventory, row.target_record_id)
                        if isinstance(status, str) and target and target.current_status != status:
                            await inventory.transition_status(
                                row.target_record_id,
                                to_status=status,
                                actor=actor,
                                source_type="TRACKER_IMPORT",
                                source_reference=f"import_run:{applied.id}",
                                note="Status set by tracker import.",
                                commit=False,
                            )
                        updated += 1
                self.session.add(
                    TrackerImportRow(
                        import_run_id=applied.id,
                        row_number=row.row_number,
                        row_fingerprint=row.row_fingerprint,
                        source_data=row.source_data,
                        normalized_data=row.normalized_data,
                        action=row.action,
                        target_record_id=row.target_record_id,
                    )
                )
            except Exception as exc:
                errors += 1
                self.session.add(
                    TrackerImportRow(
                        import_run_id=applied.id,
                        row_number=row.row_number,
                        row_fingerprint=row.row_fingerprint,
                        source_data=row.source_data,
                        normalized_data=row.normalized_data,
                        action=ImportRowAction.ERROR.value,
                        error_details=[
                            {
                                "code": ImportErrorCode.ROW_PERSIST_FAILED.value,
                                "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                            }
                        ],
                    )
                )

        applied.inserted_count = inserted
        applied.updated_count = updated
        applied.error_count = errors
        applied.status = (
            ImportRunStatus.COMPLETED_WITH_ERRORS.value
            if errors
            else ImportRunStatus.COMPLETED.value
        )
        applied.completed_at = utcnow()
        plan.status = ImportRunStatus.COMPLETED.value
        TRACKER_IMPORT_ERRORS_TOTAL.inc(errors)
        add_licensing_audit(
            self.session,
            actor=actor,
            entity_type="tracker_import_run",
            entity_id=applied.id,
            action="tracker_import_applied",
            after={"inserted": inserted, "updated": updated, "errors": errors},
        )
        await self.session.commit()
        return {
            "import_run_id": str(applied.id),
            "plan_run_id": str(plan.id),
            "status": applied.status,
            "inserted": inserted,
            "updated": updated,
            "errors": errors,
        }

    async def report(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = await self.session.get(TrackerImportRun, run_id)
        if run is None:
            raise NotFoundError("Import run not found.")
        rows = list(
            await self.session.scalars(
                select(TrackerImportRow)
                .where(TrackerImportRow.import_run_id == run.id)
                .order_by(TrackerImportRow.row_number)
            )
        )
        return {
            "id": str(run.id),
            "source_filename": run.source_filename,
            "source_sha256": run.source_sha256,
            "status": run.status,
            "dry_run": run.dry_run,
            "sheet_name": run.sheet_name,
            "detected_headers": run.detected_headers,
            "mapping_config": run.mapping_config,
            "counts": {
                "inserted": run.inserted_count,
                "updated": run.updated_count,
                "skipped": run.skipped_count,
                "errors": run.error_count,
                "conflicts": run.conflict_count,
            },
            "initiated_by_actor": run.initiated_by_actor,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "rows": [
                {
                    "row_number": row.row_number,
                    "action": row.action,
                    "row_fingerprint": row.row_fingerprint[:16],
                    "target_record_id": (
                        str(row.target_record_id) if row.target_record_id else None
                    ),
                    "normalized_data": row.normalized_data,
                    "error_details": row.error_details,
                }
                for row in rows
            ],
        }
