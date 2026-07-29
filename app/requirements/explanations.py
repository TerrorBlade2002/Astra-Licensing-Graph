"""Plain-language explanation rendering for advisory results.

Explanations are assembled from rule-authored templates plus the facts actually
consulted. Two rules govern the wording:

* Nothing is stated as a legal conclusion. Templates are authored in hedged
  language and the renderer prefixes an advisory banner.
* Every claim is traceable. The explanation lists the facts used, the facts still
  missing, and the next action, so a reader can see *why* rather than being asked
  to trust the output.

Template substitution is deliberately limited to ``{fact_path}`` placeholders
resolved from the fact dictionary. There is no expression language.
"""

from __future__ import annotations

import re
from typing import Any, Final

from app.requirements.taxonomy import RequirementOutcome

_PLACEHOLDER: Final = re.compile(r"\{([a-z][a-z0-9_.]*)\}")

ADVISORY_BANNER: Final = (
    "Advisory analysis for internal compliance planning. This is not legal advice "
    "and is not a determination that a licence is or is not required."
)

#: Reader-facing summary per outcome.
OUTCOME_SUMMARY: Final[dict[str, str]] = {
    RequirementOutcome.LIKELY_REQUIRED.value: (
        "A licence or authorisation is likely required in this jurisdiction."
    ),
    RequirementOutcome.POSSIBLY_REQUIRED.value: (
        "A licence may be required. The available facts point toward a requirement "
        "but at least one material fact is unresolved."
    ),
    RequirementOutcome.LIKELY_NOT_REQUIRED.value: (
        "A licence appears not to be required on the facts recorded."
    ),
    RequirementOutcome.COUNSEL_REVIEW.value: (
        "This jurisdiction needs legal review before any conclusion is drawn."
    ),
    RequirementOutcome.OUT_OF_SCOPE.value: (
        "This jurisdiction is outside the assessed operating footprint."
    ),
    RequirementOutcome.INSUFFICIENT_INFORMATION.value: (
        "There is not enough information to form even a provisional view."
    ),
}

#: Suggested next operational step per outcome.
OUTCOME_NEXT_ACTION: Final[dict[str, str]] = {
    RequirementOutcome.LIKELY_REQUIRED.value: (
        "Compliance review, then open an initial-licence obligation if confirmed."
    ),
    RequirementOutcome.POSSIBLY_REQUIRED.value: (
        "Resolve the missing facts, then re-evaluate. Counsel review if the facts "
        "confirm a triggering activity."
    ),
    RequirementOutcome.LIKELY_NOT_REQUIRED.value: (
        "Compliance review and, per policy, counsel confirmation before recording "
        "a no-action decision with a review date."
    ),
    RequirementOutcome.COUNSEL_REVIEW.value: "Route to counsel for legal applicability review.",
    RequirementOutcome.OUT_OF_SCOPE.value: (
        "No action while the jurisdiction remains outside the operating footprint."
    ),
    RequirementOutcome.INSUFFICIENT_INFORMATION.value: (
        "Raise internal information requests for the missing facts."
    ),
}


def _humanize_path(path: str) -> str:
    # ASCII only: explanations are exported to CSV/XLSX worksheets that may be
    # opened with a legacy codepage on Windows.
    return path.replace("_", " ").replace(".", " - ")


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list | tuple | set):
        items = [str(item).replace("_", " ") for item in value]
        return ", ".join(items) if items else "none recorded"
    if value is None:
        return "not recorded"
    return str(value)


def render_template(template: str, facts: dict[str, Any]) -> str:
    """Substitute ``{fact_path}`` placeholders, leaving unknowns clearly marked."""

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        if path in facts:
            return _format_value(facts[path])
        # Fall back to a dotted lookup so templates can address nested facts.
        current: Any = facts
        for segment in path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                return "[not recorded]"
        return _format_value(current)

    return _PLACEHOLDER.sub(replace, template)


def build_explanation(
    *,
    outcome: str,
    jurisdiction_name: str,
    rule_statements: list[str],
    facts_used: dict[str, Any],
    missing_facts: list[str],
    filing_channels: list[str],
    citations: list[dict[str, Any]],
    freshness_status: str,
    conflict_note: str | None = None,
    counsel_reason: str | None = None,
) -> str:
    """Assemble the human-readable explanation stored on a result."""
    lines: list[str] = [ADVISORY_BANNER, ""]
    lines.append(f"Jurisdiction: {jurisdiction_name}")
    lines.append(f"Outcome: {outcome}")
    lines.append("")
    lines.append(OUTCOME_SUMMARY.get(outcome, "No summary available for this outcome."))

    if rule_statements:
        lines.extend(["", "Why:"])
        lines.extend(f"- {statement}" for statement in rule_statements)

    if facts_used:
        lines.extend(["", "Facts used:"])
        lines.extend(
            f"- {_humanize_path(path)}: {_format_value(value)}"
            for path, value in sorted(facts_used.items())
        )

    if missing_facts:
        lines.extend(["", "Missing facts:"])
        lines.extend(f"- {_humanize_path(path)}" for path in missing_facts)

    lines.extend(["", "Filing channel:"])
    if filing_channels:
        lines.extend(f"- {channel}" for channel in filing_channels)
    else:
        lines.append("- UNKNOWN (channel not established by the matched rules)")

    lines.extend(["", "Sources:"])
    if citations:
        for citation in citations:
            verified = citation.get("last_verified_at") or "never verified"
            detail = f" — {citation['citation_detail']}" if citation.get("citation_detail") else ""
            lines.append(
                f"- {citation.get('title', 'Untitled source')} "
                f"[{citation.get('authority_level', 'UNVERIFIED')}], "
                f"verified {verified}{detail}"
            )
    else:
        lines.append("- No source is cited. This result cannot support a decision.")

    lines.extend(["", f"Source freshness: {freshness_status}"])

    if conflict_note:
        lines.extend(["", f"Conflict: {conflict_note}"])
    if counsel_reason:
        lines.extend(["", f"Counsel review: {counsel_reason}"])

    lines.extend(
        ["", "Next action:", f"- {OUTCOME_NEXT_ACTION.get(outcome, 'Compliance review.')}"]
    )
    return "\n".join(lines)


__all__ = [
    "ADVISORY_BANNER",
    "OUTCOME_NEXT_ACTION",
    "OUTCOME_SUMMARY",
    "build_explanation",
    "render_template",
]
