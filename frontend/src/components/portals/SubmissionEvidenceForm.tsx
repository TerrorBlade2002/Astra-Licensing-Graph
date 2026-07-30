import { useState } from "react";

export type EvidenceInput = {
  evidence_type: string;
  confirmation_number?: string;
  filing_reference?: string;
  submission_status?: string;
  source_document_id?: string;
};

export function SubmissionEvidenceForm({
  pending,
  onSubmit,
}: {
  pending?: boolean;
  onSubmit: (value: EvidenceInput) => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [reference, setReference] = useState("");
  const [documentId, setDocumentId] = useState("");
  return (
    <form
      className="panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          evidence_type: "PORTAL_CONFIRMATION",
          confirmation_number: confirmation || undefined,
          filing_reference: reference || undefined,
          submission_status: "SUBMITTED",
          source_document_id: documentId || undefined,
        });
      }}
    >
      <h2>Record governed submission evidence</h2>
      <label>
        Confirmation number
        <input
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      <label>
        Filing reference
        <input
          value={reference}
          onChange={(event) => setReference(event.target.value)}
        />
      </label>
      <label>
        Approved evidence document UUID
        <input
          value={documentId}
          onChange={(event) => setDocumentId(event.target.value)}
        />
      </label>
      <button
        disabled={pending || (!confirmation && !reference && !documentId)}
      >
        Record evidence
      </button>
      <small className="muted">
        Do not enter passwords, MFA codes, payment details, or browser state.
      </small>
    </form>
  );
}
