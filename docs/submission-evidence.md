# Submission evidence

Final submission is always performed by the assigned human. Astra has no final-submit browser action and no final-submit API transport method.

After the human action, the result is one of:

- `CONFIRMED`: a reviewed confirmation page plus a confirmation number, filing reference, or approved entity-matched evidence document exists;
- `FAILED`: the portal clearly rejected the action;
- `SUBMISSION_RESULT_PENDING`: the outcome is ambiguous.

An ambiguous outcome is never retried. A single reconciliation-only job compares confirmation page state, filing status, confirmation references, receipts, and later regulator/vendor evidence.

Verified evidence advances the compliance case only to `SUBMITTED_TO_REGULATOR` or `SUBMITTED_TO_VENDOR` and creates a follow-up deadline. It does not mark the license renewed, accepted, approved, or complete. Evidence documents must be active, approved, current, and linked to the same legal entity.

