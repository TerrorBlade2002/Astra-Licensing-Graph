import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { ComplianceCase } from "../types";

type Timeline = {
  id: string;
  from_stage: string | null;
  to_stage: string;
  actor_id: string | null;
  reason: string | null;
  occurred_at: string;
};
export function ComplianceCasePage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const record = useQuery({
    queryKey: ["case", id],
    queryFn: () => api<ComplianceCase>(`/compliance-cases/${id}`),
    enabled: !!id,
  });
  const timeline = useQuery({
    queryKey: ["case-timeline", id],
    queryFn: () => api<Timeline[]>(`/compliance-cases/${id}/timeline`),
    enabled: !!id,
  });
  const transitions = useQuery({
    queryKey: ["case-transitions", id],
    queryFn: () =>
      api<{ transitions: string[] }>(
        `/compliance-cases/${id}/available-transitions`,
      ),
    enabled: !!id,
  });
  const move = useMutation({
    mutationFn: (to_stage: string) =>
      api(`/compliance-cases/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({
          to_stage,
          reason: "Confirmed in case workspace.",
          evidence: {},
        }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["case", id] }),
  });
  if (record.isLoading) return <Loading />;
  if (record.error) return <ErrorState error={record.error} />;
  const item = record.data!;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">{item.case_type}</span>
          <h1>{item.case_key}</h1>
          <p>
            Vendor receipt, regulator approval, and renewed evidence remain
            distinct stages.
          </p>
        </div>
        <Status value={item.status} />
      </div>
      <div className="case-stage-banner">
        <span>Current stage</span>
        <strong>{item.current_stage}</strong>
        <small>{item.assigned_owner ?? "Unassigned"}</small>
      </div>
      <div className="split">
        <section className="panel">
          <h2>Permitted next stages</h2>
          <div className="stacked-actions">
            {transitions.data?.transitions.map((stage) => (
              <button
                key={stage}
                disabled={move.isPending}
                onClick={() => move.mutate(stage)}
              >
                {stage.replaceAll("_", " ")}
              </button>
            ))}
          </div>
          <p className="muted">
            Evidence-gated transitions are rejected by the backend when evidence
            is missing.
          </p>
        </section>
        <section className="panel">
          <h2>Audit timeline</h2>
          {timeline.data?.map((event) => (
            <div className="timeline-row" key={event.id}>
              <Status value={event.to_stage} />
              <strong>
                {event.from_stage ?? "Opened"} → {event.to_stage}
              </strong>
              <small>
                {new Date(event.occurred_at).toLocaleString()} ·{" "}
                {event.actor_id}
              </small>
              <p>{event.reason}</p>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
