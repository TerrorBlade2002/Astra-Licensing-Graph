import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import {
  SubmissionEvidenceForm,
  type EvidenceInput,
} from "../components/portals/SubmissionEvidenceForm";
import type {
  PortalAttestation,
  PortalPayment,
  PortalSubmissionEvidence,
} from "../types";

export function SubmissionEvidencePage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const [attestationEvidence, setAttestationEvidence] = useState("");
  const [attestationResultPage, setAttestationResultPage] = useState("");
  const [paymentReference, setPaymentReference] = useState("");
  const [receiptDocumentId, setReceiptDocumentId] = useState("");
  const [outcome, setOutcome] = useState("CONFIRMED");
  const [resultPage, setResultPage] = useState("confirmation");
  const [confirmationNumber, setConfirmationNumber] = useState("");
  const [filingReference, setFilingReference] = useState("");
  const [ambiguous, setAmbiguous] = useState(false);
  const evidence = useQuery({
    queryKey: ["submission-evidence", id],
    queryFn: () =>
      api<PortalSubmissionEvidence[]>(`/portal-runs/${id}/submission-evidence`),
    enabled: !!id,
  });
  const attestations = useQuery({
    queryKey: ["portal-attestations", id],
    queryFn: () => api<PortalAttestation[]>(`/portal-runs/${id}/attestations`),
    enabled: !!id,
  });
  const payment = useQuery({
    queryKey: ["portal-payment", id],
    queryFn: () => api<PortalPayment | null>(`/portal-runs/${id}/payment`),
    enabled: !!id,
  });
  const create = useMutation({
    mutationFn: (value: EvidenceInput) =>
      api(`/portal-runs/${id}/submission-evidence`, {
        method: "POST",
        body: JSON.stringify(value),
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["submission-evidence", id] }),
  });
  const refreshControls = () => {
    void client.invalidateQueries({ queryKey: ["portal-attestations", id] });
    void client.invalidateQueries({ queryKey: ["portal-payment", id] });
    void client.invalidateQueries({ queryKey: ["submission-evidence", id] });
    void client.invalidateQueries({ queryKey: ["portal-run", id] });
  };
  const completeAttestation = useMutation({
    mutationFn: (attestationId: string) =>
      api(`/portal-attestations/${attestationId}/record-human-completion`, {
        method: "POST",
        body: JSON.stringify({
          resulting_page_category: attestationResultPage,
          evidence_reference: attestationEvidence,
        }),
      }),
    onSuccess: refreshControls,
  });
  const approvePayment = useMutation({
    mutationFn: (paymentId: string) =>
      api(`/portal-payments/${paymentId}/approve`, { method: "POST" }),
    onSuccess: refreshControls,
  });
  const recordPayment = useMutation({
    mutationFn: (paymentId: string) =>
      api(`/portal-payments/${paymentId}/record-external-payment`, {
        method: "POST",
        body: JSON.stringify({
          payment_reference_redacted: paymentReference || undefined,
          receipt_document_id: receiptDocumentId || undefined,
        }),
      }),
    onSuccess: refreshControls,
  });
  const captureResult = useMutation({
    mutationFn: () =>
      api(`/portal-runs/${id}/capture-submission-result`, {
        method: "POST",
        body: JSON.stringify({
          outcome,
          resulting_page_category: resultPage,
          ambiguous,
          confirmation_number: confirmationNumber || undefined,
          filing_reference: filingReference || undefined,
        }),
      }),
    onSuccess: refreshControls,
  });
  if (evidence.isLoading || attestations.isLoading || payment.isLoading)
    return <Loading />;
  if (evidence.error || attestations.error || payment.error)
    return (
      <ErrorState
        error={evidence.error ?? attestations.error ?? payment.error}
      />
    );
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Governed proof</span>
          <h1>Submission evidence</h1>
          <p>
            <Link to={`/portal-runs/${id}`}>Return to portal run</Link>
          </p>
        </div>
      </div>
      <div className="split">
        <section className="panel">
          <h2>Recorded evidence</h2>
          {evidence.data?.map((item) => (
            <div className="timeline-row" key={item.id}>
              <Status value={item.submission_status ?? item.evidence_type} />
              <strong>{item.evidence_type.replaceAll("_", " ")}</strong>
              <small>
                Confirmation {item.confirmation_number ?? "—"} · Filing{" "}
                {item.filing_reference ?? "—"}
              </small>
              <p>
                {item.verified_at
                  ? `Verified ${new Date(item.verified_at).toLocaleString()}`
                  : "Awaiting verification"}
              </p>
            </div>
          ))}
        </section>
        <SubmissionEvidenceForm
          pending={create.isPending}
          onSubmit={(value) => create.mutate(value)}
        />
      </div>
      <div className="split">
        <section className="panel">
          <h2>Human attestation records</h2>
          {attestations.data?.length ? (
            attestations.data.map((item) => (
              <div className="timeline-row" key={item.id}>
                <Status value={item.status} />
                <strong>{item.attestation_type.replaceAll("_", " ")}</strong>
                {item.status === "WAITING" && (
                  <>
                    <label>
                      Resulting reviewed page category
                      <input
                        value={attestationResultPage}
                        onChange={(event) =>
                          setAttestationResultPage(event.target.value)
                        }
                      />
                    </label>
                    <label>
                      Governed evidence reference
                      <input
                        value={attestationEvidence}
                        onChange={(event) =>
                          setAttestationEvidence(event.target.value)
                        }
                      />
                    </label>
                    <button
                      disabled={
                        completeAttestation.isPending ||
                        !attestationResultPage ||
                        !attestationEvidence
                      }
                      onClick={() => completeAttestation.mutate(item.id)}
                    >
                      Record my completed attestation
                    </button>
                  </>
                )}
              </div>
            ))
          ) : (
            <p>No attestation is currently required.</p>
          )}
        </section>
        <section className="panel">
          <h2>External payment handoff</h2>
          {!payment.data ? (
            <p>No payment is currently required.</p>
          ) : (
            <>
              <Status value={payment.data.status} />
              <p>
                Expected fee{" "}
                {payment.data.expected_fee_amount ?? "review on portal"}{" "}
                {payment.data.currency ?? ""}
              </p>
              {payment.data.status === "REVIEW_REQUIRED" && (
                <button
                  disabled={approvePayment.isPending}
                  onClick={() => approvePayment.mutate(payment.data!.id)}
                >
                  Approve reviewed fee
                </button>
              )}
              {payment.data.status === "APPROVED" && (
                <>
                  <label>
                    Redacted payment reference
                    <input
                      value={paymentReference}
                      onChange={(event) =>
                        setPaymentReference(event.target.value)
                      }
                      placeholder="Reference ending 1234"
                    />
                  </label>
                  <label>
                    Approved receipt document UUID
                    <input
                      value={receiptDocumentId}
                      onChange={(event) =>
                        setReceiptDocumentId(event.target.value)
                      }
                    />
                  </label>
                  <button
                    disabled={recordPayment.isPending}
                    onClick={() => recordPayment.mutate(payment.data!.id)}
                  >
                    Record payment made outside Astra
                  </button>
                </>
              )}
            </>
          )}
        </section>
      </div>
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault();
          captureResult.mutate();
        }}
      >
        <h2>Record final human-submit outcome</h2>
        <p>
          Astra never presses the final control. Use this only after the
          assigned person acted in the portal.
        </p>
        <label>
          Outcome
          <select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
          >
            <option value="CONFIRMED">Confirmed</option>
            <option value="FAILED">Failed</option>
            <option value="UNKNOWN">Unknown</option>
          </select>
        </label>
        <label>
          Resulting page category
          <input
            value={resultPage}
            onChange={(event) => setResultPage(event.target.value)}
          />
        </label>
        <label>
          Confirmation number
          <input
            value={confirmationNumber}
            onChange={(event) => setConfirmationNumber(event.target.value)}
          />
        </label>
        <label>
          Filing reference
          <input
            value={filingReference}
            onChange={(event) => setFilingReference(event.target.value)}
          />
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={ambiguous}
            onChange={(event) => setAmbiguous(event.target.checked)}
          />
          The outcome is ambiguous—reconcile only and never retry submission
        </label>
        <button
          disabled={
            captureResult.isPending ||
            (!ambiguous &&
              outcome === "CONFIRMED" &&
              !confirmationNumber &&
              !filingReference)
          }
        >
          Record human result
        </button>
      </form>
      <p className="safety-callout">
        A submitted receipt advances the case only to regulator/vendor review.
        It never marks the license renewed.
      </p>
      {(create.error ||
        completeAttestation.error ||
        approvePayment.error ||
        recordPayment.error ||
        captureResult.error) && (
        <ErrorState
          error={
            create.error ??
            completeAttestation.error ??
            approvePayment.error ??
            recordPayment.error ??
            captureResult.error
          }
        />
      )}
    </main>
  );
}
