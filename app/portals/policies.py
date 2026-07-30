"""Fail-closed portal governance and action policy checks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.models.mixins import utcnow
from app.portals.enums import (
    APPROVED_PORTAL_STATUSES,
    AUTOMATION_LEVEL_RANK,
    AdapterStatus,
    AuthorizationStatus,
    AutomationLevel,
    PortalApprovalStatus,
    PortalReviewStatus,
)

ABSOLUTELY_PROHIBITED_ACTIONS = frozenset(
    {
        "ACCEPT_TERMS",
        "ENTER_MFA",
        "SOLVE_CAPTCHA",
        "ATTEST",
        "SIGN",
        "ENTER_PAYMENT_CREDENTIALS",
        "AUTHORIZE_PAYMENT",
        "FINAL_SUBMIT",
    }
)

ACTION_MINIMUM_LEVEL = {
    "NAVIGATE": AutomationLevel.NAVIGATION_ASSIST.value,
    "ENTER_FIELD": AutomationLevel.ASSISTED_ENTRY.value,
    "UPLOAD_DOCUMENT": AutomationLevel.UPLOAD_ASSIST.value,
    "SAVE_DRAFT": AutomationLevel.ASSISTED_ENTRY.value,
    "VALIDATE": AutomationLevel.PRE_SUBMISSION_ASSIST.value,
    "CAPTURE_PRE_SUBMISSION": AutomationLevel.PRE_SUBMISSION_ASSIST.value,
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def approval_is_current(
    *,
    portal_status: str,
    review_status: str,
    valid_from: datetime | None,
    valid_to: datetime | None,
    terms_expires_at: datetime | None,
    now: datetime | None = None,
) -> PolicyDecision:
    moment = now or utcnow()
    if portal_status not in APPROVED_PORTAL_STATUSES:
        return PolicyDecision(False, f"Portal status {portal_status} does not permit assistance.")
    if review_status != PortalReviewStatus.APPROVED.value:
        return PolicyDecision(False, "Portal review is not approved.")
    if valid_from and valid_from > moment:
        return PolicyDecision(False, "Portal review is not yet valid.")
    if valid_to and valid_to <= moment:
        return PolicyDecision(False, "Portal review has expired.")
    if terms_expires_at and terms_expires_at <= moment:
        return PolicyDecision(False, "Portal terms review has expired.")
    return PolicyDecision(True, "Portal approval and review are current.")


def authorization_is_current(
    *,
    status: str,
    expires_at: datetime | None,
    filing_type: str,
    legal_entity_id: object,
    authorized_filing_types: Sequence[str],
    authorized_entity_ids: Sequence[object],
    now: datetime | None = None,
) -> PolicyDecision:
    if status != AuthorizationStatus.ACTIVE.value:
        return PolicyDecision(False, "Operator authorization is not active.")
    if expires_at and expires_at <= (now or utcnow()):
        return PolicyDecision(False, "Operator authorization has expired.")
    if authorized_filing_types and filing_type not in authorized_filing_types:
        return PolicyDecision(False, "Operator is not authorized for this filing type.")
    if authorized_entity_ids and legal_entity_id not in authorized_entity_ids:
        return PolicyDecision(False, "Operator is not authorized for this legal entity.")
    return PolicyDecision(True, "Operator authorization is current.")


def action_is_allowed(
    *,
    action: str,
    run_level: str,
    portal_level: str,
    allowed_actions: dict[str, object],
    prohibited_actions: dict[str, object],
    human_only: bool = False,
) -> PolicyDecision:
    action = action.upper()
    if action in ABSOLUTELY_PROHIBITED_ACTIONS:
        return PolicyDecision(False, f"{action} is always human-only.")
    if human_only:
        return PolicyDecision(False, "The field or action is marked human-only.")
    if bool(prohibited_actions.get(action)):
        return PolicyDecision(False, f"Portal review prohibits {action}.")
    if allowed_actions and not bool(allowed_actions.get(action)):
        return PolicyDecision(False, f"Portal review does not explicitly allow {action}.")
    minimum = ACTION_MINIMUM_LEVEL.get(action)
    if minimum:
        effective_rank = min(
            AUTOMATION_LEVEL_RANK.get(run_level, -1),
            AUTOMATION_LEVEL_RANK.get(portal_level, -1),
        )
        if effective_rank < AUTOMATION_LEVEL_RANK[minimum]:
            return PolicyDecision(False, f"{action} exceeds the approved automation level.")
    return PolicyDecision(True, f"{action} is within the approved assistance boundary.")


def portal_can_activate(status: str) -> bool:
    return status not in {
        PortalApprovalStatus.AUTOMATION_PROHIBITED.value,
        PortalApprovalStatus.TEMPORARILY_SUSPENDED.value,
        PortalApprovalStatus.EXPIRED.value,
        PortalApprovalStatus.RETIRED.value,
    }


def adapter_is_active(status: str) -> bool:
    return status == AdapterStatus.ACTIVE.value
