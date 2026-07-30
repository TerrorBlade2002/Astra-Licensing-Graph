import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { PortalHandoff } from "../types";

export function PortalHandoffPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const [confirmation, setConfirmation] = useState("");
  const [evidence, setEvidence] = useState("");
  const [pageCategory, setPageCategory] = useState("");
  const handoff = useQuery({
    queryKey: ["portal-handoff", id],
    queryFn: () => api<PortalHandoff>(`/handoffs/${id}`),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const accept = useMutation({
    mutationFn: () => api(`/handoffs/${id}/accept`, { method: "POST" }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-handoff", id] }),
  });
  const complete = useMutation({
    mutationFn: () => {
      const path =
        handoff.data?.handoff_type === "SIGNATURE"
          ? `/portal-signature-handoffs/${id}/record-human-completion`
          : `/handoffs/${id}/complete`;
      return api(path, {
        method: "POST",
        body: JSON.stringify({
          result: "HUMAN_ACTION_REPORTED",
          operator_confirmation: confirmation,
          evidence_reference: evidence || undefined,
          observed_page_category: pageCategory || undefined,
        }),
      });
    },
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-handoff", id] }),
  });
  if (handoff.isLoading) return <Loading />;
  if (handoff.error) return <ErrorState error={handoff.error} />;
  const item = handoff.data!;
  const dedicatedWorkflow = ["ATTESTATION", "PAYMENT", "FINAL_SUBMIT"].includes(
    item.handoff_type,
  );
  const signatureWorkflow = item.handoff_type === "SIGNATURE";
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Human-only action</span>
          <h1>{item.handoff_type.replaceAll("_", " ")}</h1>
          <p>
            <Link to={`/portal-runs/${item.portal_run_id}`}>
              Return to portal run
            </Link>
          </p>
        </div>
        <Status value={item.status} />
      </div>
      <section className="panel">
        <h2>What you must do</h2>
        <p>
          Use only your own authorized portal account and complete only the
          named action. Automation is paused and cannot accept terms, supply
          MFA, solve CAPTCHA, attest, pay, sign, or submit for you.
        </p>
        <p className="safety-callout">
          Never paste a password, MFA code, card number, cookie, token, or
          browser-state value into Astra.
        </p>
        {item.status === "REQUESTED" && (
          <button disabled={accept.isPending} onClick={() => accept.mutate()}>
            Accept this assigned action
          </button>
        )}
      </section>
      {item.status === "ACTIVE" && dedicatedWorkflow && (
        <section className="panel">
          <h2>Record the governed human result</h2>
          <p>
            This action is recorded through the dedicated attestation, external
            payment, or submission-evidence control. It cannot be completed by a
            generic browser confirmation.
          </p>
          <Link to={`/portal-runs/${item.portal_run_id}/submission-evidence`}>
            Open governed evidence controls
          </Link>
        </section>
      )}
      {item.status === "ACTIVE" && !dedicatedWorkflow && (
        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            complete.mutate();
          }}
        >
          <h2>
            {signatureWorkflow
              ? "Record governed signed-form evidence"
              : "Request verification"}
          </h2>
          <label>
            Resulting reviewed page category
            <input
              value={pageCategory}
              onChange={(event) => setPageCategory(event.target.value)}
              placeholder="confirmation, filing, validation…"
            />
          </label>
          <label>
            Non-sensitive confirmation
            <textarea
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
          <label>
            Governed evidence reference
            <input
              value={evidence}
              onChange={(event) => setEvidence(event.target.value)}
            />
          </label>
          <button
            disabled={
              complete.isPending ||
              !evidence ||
              (!signatureWorkflow && (!confirmation || !pageCategory))
            }
          >
            {signatureWorkflow
              ? "Record signed-form evidence"
              : "Request portal-state verification"}
          </button>
          <small>
            Clicking this does not itself prove completion. The resulting portal
            contract is verified before automation can resume.
          </small>
        </form>
      )}
      {(accept.error || complete.error) && (
        <ErrorState error={accept.error ?? complete.error} />
      )}
    </main>
  );
}
