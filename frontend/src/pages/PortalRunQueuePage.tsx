import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { PortalRun } from "../types";

export function PortalRunQueuePage() {
  const client = useQueryClient();
  const [caseId, setCaseId] = useState("");
  const [portalId, setPortalId] = useState("");
  const [filingType, setFilingType] = useState("");
  const [operatorId, setOperatorId] = useState("");
  const runs = useQuery({
    queryKey: ["portal-runs"],
    queryFn: () => api<PortalRun[]>("/portal-runs"),
    refetchInterval: 10000,
  });
  const create = useMutation({
    mutationFn: () =>
      api(`/compliance-cases/${caseId}/portal-runs`, {
        method: "POST",
        body: JSON.stringify({
          portal_definition_id: portalId,
          filing_type: filingType,
          automation_level: "PRE_SUBMISSION_ASSIST",
          assigned_operator_id: operatorId || undefined,
        }),
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-runs"] }),
  });
  if (runs.isLoading) return <Loading />;
  if (runs.error) return <ErrorState error={runs.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Human supervised</span>
          <h1>Portal run queue</h1>
          <p>
            Submission, attestation, payment, MFA, CAPTCHA, and terms always
            stop for the assigned person.
          </p>
        </div>
      </div>
      <section className="panel wide">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Case</th>
                <th>Filing</th>
                <th>Stage</th>
                <th>Operator</th>
                <th>Deadline</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {runs.data?.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link to={`/portal-runs/${run.id}`}>{run.run_key}</Link>
                  </td>
                  <td>{run.compliance_case_id.slice(0, 8)}</td>
                  <td>{run.filing_type}</td>
                  <td>{run.current_stage}</td>
                  <td>
                    {run.assigned_operator_id?.slice(0, 8) ?? "Unassigned"}
                  </td>
                  <td>
                    {run.deadline_at
                      ? new Date(run.deadline_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td>
                    <Status value={run.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <h2>Create run from submission-ready case</h2>
        <label>
          Compliance case UUID
          <input
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
          />
        </label>
        <label>
          Approved portal UUID
          <input
            value={portalId}
            onChange={(event) => setPortalId(event.target.value)}
          />
        </label>
        <label>
          Filing type
          <input
            value={filingType}
            onChange={(event) => setFilingType(event.target.value)}
          />
        </label>
        <label>
          Authorized operator UUID
          <input
            value={operatorId}
            onChange={(event) => setOperatorId(event.target.value)}
          />
        </label>
        <button
          disabled={create.isPending || !caseId || !portalId || !filingType}
        >
          Create governed run
        </button>
        {create.error && <ErrorState error={create.error} />}
      </form>
    </main>
  );
}
