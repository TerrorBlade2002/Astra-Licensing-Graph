"""Compliance-case stage machine.

The transition matrix is explicit rather than permissive. Three classes of rule
are enforced here because each corresponds to a real failure mode:

* **No skipping signature.** When a form requires a signature, a case cannot reach
  submission without passing through the signature stages.
* **No completion without evidence.** ``COMPLETED`` requires either renewed
  evidence or an explicitly recorded close reason.
* **Vendor receipt is not regulator approval.** ``SUBMITTED_TO_VENDOR`` and
  ``SUBMITTED_TO_REGULATOR`` are distinct stages, and neither implies approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.licensing.enums import CaseStage, CaseStatus

S = CaseStage

#: Allowed forward, corrective, and abort transitions.
#:
#: Deliberately not a strict linear chain: real cases loop (a deficiency sends work
#: back to information gathering) and skip (a direct-to-regulator case has no
#: vendor outreach). What is *not* allowed is jumping over a control point.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    S.DUE_IDENTIFIED.value: frozenset({S.CASE_PLANNING.value, S.BLOCKED.value, S.CANCELLED.value}),
    S.CASE_PLANNING.value: frozenset(
        {
            S.VENDOR_OUTREACH_PENDING.value,
            # Direct-to-regulator cases never touch a vendor.
            S.DOCUMENT_CHECKLIST_RECEIVED.value,
            S.DOCUMENTS_PENDING.value,
            S.INTERNAL_INFORMATION_PENDING.value,
            S.FORM_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.VENDOR_OUTREACH_PENDING.value: frozenset(
        {S.VENDOR_OUTREACH_SENT.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.VENDOR_OUTREACH_SENT.value: frozenset(
        {
            S.VENDOR_QUESTIONS.value,
            S.DOCUMENT_CHECKLIST_RECEIVED.value,
            S.FORM_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.VENDOR_QUESTIONS.value: frozenset(
        {
            S.INTERNAL_INFORMATION_PENDING.value,
            S.ANSWERS_READY.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.INTERNAL_INFORMATION_PENDING.value: frozenset(
        {S.ANSWERS_READY.value, S.VENDOR_QUESTIONS.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.ANSWERS_READY.value: frozenset(
        {
            S.ANSWERS_SENT.value,
            S.INTERNAL_INFORMATION_PENDING.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.ANSWERS_SENT.value: frozenset(
        {
            S.DOCUMENT_CHECKLIST_RECEIVED.value,
            S.VENDOR_QUESTIONS.value,
            S.FORM_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.DOCUMENT_CHECKLIST_RECEIVED.value: frozenset(
        {S.DOCUMENTS_PENDING.value, S.PACKET_BUILDING.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.DOCUMENTS_PENDING.value: frozenset(
        {S.PACKET_BUILDING.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.PACKET_BUILDING.value: frozenset(
        {
            S.PACKET_READY_FOR_REVIEW.value,
            S.DOCUMENTS_PENDING.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.PACKET_READY_FOR_REVIEW.value: frozenset(
        {
            S.PACKET_APPROVED.value,
            # Rejection returns to building, producing a new packet version.
            S.PACKET_BUILDING.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.PACKET_APPROVED.value: frozenset(
        {S.PACKET_SENT.value, S.PACKET_BUILDING.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.PACKET_SENT.value: frozenset(
        {
            S.FORM_RECEIVED.value,
            S.VENDOR_QUESTIONS.value,
            S.VENDOR_VALIDATION.value,
            S.SUBMISSION_PENDING.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.FORM_RECEIVED.value: frozenset(
        {S.FORM_PREPARATION.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.FORM_PREPARATION.value: frozenset(
        {
            S.FORM_MISSING_INFORMATION.value,
            S.FORM_READY_FOR_REVIEW.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.FORM_MISSING_INFORMATION.value: frozenset(
        {
            S.FORM_PREPARATION.value,
            S.INTERNAL_INFORMATION_PENDING.value,
            S.FORM_READY_FOR_REVIEW.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.FORM_READY_FOR_REVIEW.value: frozenset(
        {
            S.SIGNATURE_PENDING.value,
            # Only permitted when no signature is required; guarded below.
            S.SUBMISSION_PENDING.value,
            S.FORM_PREPARATION.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.SIGNATURE_PENDING.value: frozenset(
        {S.SIGNED_FORM_RECEIVED.value, S.FORM_PREPARATION.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.SIGNED_FORM_RECEIVED.value: frozenset(
        {S.SUBMISSION_PENDING.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.SUBMISSION_PENDING.value: frozenset(
        {
            S.SUBMITTED_TO_VENDOR.value,
            S.SUBMITTED_TO_REGULATOR.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.SUBMITTED_TO_VENDOR.value: frozenset(
        {
            S.VENDOR_VALIDATION.value,
            S.SUBMITTED_TO_REGULATOR.value,
            S.DEFICIENCY_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.SUBMITTED_TO_REGULATOR.value: frozenset(
        {
            S.REGULATOR_REVIEW.value,
            S.DEFICIENCY_RECEIVED.value,
            S.RENEWED_EVIDENCE_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.VENDOR_VALIDATION.value: frozenset(
        {
            S.SUBMITTED_TO_REGULATOR.value,
            S.REGULATOR_REVIEW.value,
            S.DEFICIENCY_RECEIVED.value,
            S.FORM_PREPARATION.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.REGULATOR_REVIEW.value: frozenset(
        {
            S.DEFICIENCY_RECEIVED.value,
            S.RENEWED_EVIDENCE_RECEIVED.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.DEFICIENCY_RECEIVED.value: frozenset(
        {
            S.INTERNAL_INFORMATION_PENDING.value,
            S.DOCUMENTS_PENDING.value,
            S.FORM_PREPARATION.value,
            S.PACKET_BUILDING.value,
            S.BLOCKED.value,
            S.CANCELLED.value,
        }
    ),
    S.RENEWED_EVIDENCE_RECEIVED.value: frozenset(
        {S.INVENTORY_UPDATE_PENDING.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    S.INVENTORY_UPDATE_PENDING.value: frozenset(
        {S.COMPLETED.value, S.BLOCKED.value, S.CANCELLED.value}
    ),
    # Blocked returns to wherever work resumes; the service records the reason.
    S.BLOCKED.value: frozenset(
        {
            S.CASE_PLANNING.value,
            S.VENDOR_OUTREACH_PENDING.value,
            S.VENDOR_QUESTIONS.value,
            S.INTERNAL_INFORMATION_PENDING.value,
            S.DOCUMENTS_PENDING.value,
            S.PACKET_BUILDING.value,
            S.FORM_PREPARATION.value,
            S.SIGNATURE_PENDING.value,
            S.SUBMISSION_PENDING.value,
            S.REGULATOR_REVIEW.value,
            S.CANCELLED.value,
        }
    ),
    S.COMPLETED.value: frozenset(),
    S.CANCELLED.value: frozenset(),
}

#: Stages requiring recorded evidence before they may be entered. The evidence
#: keys are asserted by the service; the matrix only declares the requirement.
STAGE_EVIDENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    S.VENDOR_OUTREACH_SENT.value: ("outreach_reference",),
    S.ANSWERS_SENT.value: ("answer_reference",),
    S.PACKET_APPROVED.value: ("document_packet_id",),
    S.PACKET_SENT.value: ("document_packet_id",),
    S.SIGNED_FORM_RECEIVED.value: ("signed_document_id",),
    S.SUBMITTED_TO_VENDOR.value: ("submission_reference",),
    S.SUBMITTED_TO_REGULATOR.value: ("submission_reference",),
    S.RENEWED_EVIDENCE_RECEIVED.value: ("renewed_evidence_document_id",),
}

#: Stage -> case status, so the two never drift apart.
STAGE_STATUS: dict[str, str] = {
    S.DUE_IDENTIFIED.value: CaseStatus.OPEN.value,
    S.CASE_PLANNING.value: CaseStatus.IN_PROGRESS.value,
    S.VENDOR_OUTREACH_PENDING.value: CaseStatus.IN_PROGRESS.value,
    S.VENDOR_OUTREACH_SENT.value: CaseStatus.WAITING_VENDOR.value,
    S.VENDOR_QUESTIONS.value: CaseStatus.WAITING_INTERNAL.value,
    S.INTERNAL_INFORMATION_PENDING.value: CaseStatus.WAITING_INTERNAL.value,
    S.ANSWERS_READY.value: CaseStatus.IN_PROGRESS.value,
    S.ANSWERS_SENT.value: CaseStatus.WAITING_VENDOR.value,
    S.DOCUMENT_CHECKLIST_RECEIVED.value: CaseStatus.IN_PROGRESS.value,
    S.DOCUMENTS_PENDING.value: CaseStatus.WAITING_INTERNAL.value,
    S.PACKET_BUILDING.value: CaseStatus.IN_PROGRESS.value,
    S.PACKET_READY_FOR_REVIEW.value: CaseStatus.IN_PROGRESS.value,
    S.PACKET_APPROVED.value: CaseStatus.IN_PROGRESS.value,
    S.PACKET_SENT.value: CaseStatus.WAITING_VENDOR.value,
    S.FORM_RECEIVED.value: CaseStatus.IN_PROGRESS.value,
    S.FORM_PREPARATION.value: CaseStatus.IN_PROGRESS.value,
    S.FORM_MISSING_INFORMATION.value: CaseStatus.WAITING_INTERNAL.value,
    S.FORM_READY_FOR_REVIEW.value: CaseStatus.IN_PROGRESS.value,
    S.SIGNATURE_PENDING.value: CaseStatus.WAITING_SIGNATURE.value,
    S.SIGNED_FORM_RECEIVED.value: CaseStatus.IN_PROGRESS.value,
    S.SUBMISSION_PENDING.value: CaseStatus.WAITING_SUBMISSION.value,
    S.SUBMITTED_TO_VENDOR.value: CaseStatus.WAITING_VENDOR.value,
    S.SUBMITTED_TO_REGULATOR.value: CaseStatus.WAITING_REGULATOR.value,
    S.VENDOR_VALIDATION.value: CaseStatus.WAITING_VENDOR.value,
    S.REGULATOR_REVIEW.value: CaseStatus.WAITING_REGULATOR.value,
    S.DEFICIENCY_RECEIVED.value: CaseStatus.IN_PROGRESS.value,
    S.RENEWED_EVIDENCE_RECEIVED.value: CaseStatus.IN_PROGRESS.value,
    S.INVENTORY_UPDATE_PENDING.value: CaseStatus.IN_PROGRESS.value,
    S.COMPLETED.value: CaseStatus.COMPLETED.value,
    S.BLOCKED.value: CaseStatus.BLOCKED.value,
    S.CANCELLED.value: CaseStatus.CANCELLED.value,
}

#: Stages after which a signature can no longer be introduced without redoing the
#: form. Used to reject "sneak past signature" transitions.
_POST_SIGNATURE_STAGES = frozenset(
    {
        S.SUBMISSION_PENDING.value,
        S.SUBMITTED_TO_VENDOR.value,
        S.SUBMITTED_TO_REGULATOR.value,
    }
)

TERMINAL_STAGES = frozenset({S.COMPLETED.value, S.CANCELLED.value})


@dataclass(frozen=True, slots=True)
class TransitionCheck:
    """Outcome of validating a proposed stage change."""

    allowed: bool
    reason: str = ""
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    resulting_status: str | None = None


def validate_transition(
    *,
    from_stage: str,
    to_stage: str,
    evidence: dict[str, object] | None = None,
    signature_required: bool = False,
    signature_recorded: bool = False,
    has_renewed_evidence: bool = False,
    close_reason: str | None = None,
) -> TransitionCheck:
    """Validate a proposed stage transition against the matrix and control rules."""
    payload = evidence or {}

    if from_stage == to_stage:
        return TransitionCheck(False, reason="The case is already in that stage.")
    if from_stage in TERMINAL_STAGES:
        return TransitionCheck(
            False, reason=f"{from_stage} is terminal; reopen the case to continue work."
        )
    if to_stage not in ALLOWED_TRANSITIONS:
        return TransitionCheck(False, reason=f"Unknown stage {to_stage!r}.")
    if to_stage not in ALLOWED_TRANSITIONS.get(from_stage, frozenset()):
        return TransitionCheck(
            False,
            reason=(
                f"{from_stage} -> {to_stage} is not an allowed transition. "
                "Stages that enforce a control point cannot be skipped."
            ),
        )

    required = STAGE_EVIDENCE_REQUIREMENTS.get(to_stage, ())
    missing = tuple(key for key in required if not payload.get(key))
    if missing:
        return TransitionCheck(
            False,
            reason=f"{to_stage} requires evidence: {', '.join(missing)}.",
            missing_evidence=missing,
        )

    # A form needing a signature must not reach submission unsigned.
    if signature_required and not signature_recorded and to_stage in _POST_SIGNATURE_STAGES:
        return TransitionCheck(
            False,
            reason=(
                "This case has a form requiring an authorised signature. Record the "
                "signed document before moving to a submission stage."
            ),
        )

    # Completion demands renewed evidence or an explicit, recorded close reason.
    if to_stage == S.COMPLETED.value and not has_renewed_evidence and not close_reason:
        return TransitionCheck(
            False,
            reason=(
                "A case cannot be completed without renewed evidence or an approved close reason."
            ),
        )

    return TransitionCheck(True, resulting_status=STAGE_STATUS.get(to_stage))


def next_stages(from_stage: str) -> tuple[str, ...]:
    """Stages reachable from ``from_stage``, for driving the portal UI."""
    return tuple(sorted(ALLOWED_TRANSITIONS.get(from_stage, frozenset())))


def initial_stage() -> str:
    return S.DUE_IDENTIFIED.value


__all__ = [
    "ALLOWED_TRANSITIONS",
    "STAGE_EVIDENCE_REQUIREMENTS",
    "STAGE_STATUS",
    "TERMINAL_STAGES",
    "TransitionCheck",
    "initial_stage",
    "next_stages",
    "validate_transition",
]
