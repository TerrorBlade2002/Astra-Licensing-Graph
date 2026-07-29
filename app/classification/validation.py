"""Evidence-bound post-validation for any deterministic/model merged result."""

from app.classification.schema import ClassificationOutputV1
from app.classification.taxonomy import VALID_DESTINATIONS


def validate_evidence(
    output: ClassificationOutputV1, source_text: str, filenames: set[str]
) -> list[str]:
    errors: list[str] = []
    normalized = " ".join(source_text.split()).casefold()
    for index, item in enumerate(output.requested_information):
        if " ".join(item.evidence_quote.split()).casefold() not in normalized:
            errors.append(f"requested_information[{index}].evidence_quote is not traceable")
    for document in output.documents:
        if document.filename not in filenames:
            errors.append(f"document filename is not present in evidence: {document.filename}")
    if output.suggested_destination not in VALID_DESTINATIONS:
        errors.append("suggested_destination is not configured")
    return errors
