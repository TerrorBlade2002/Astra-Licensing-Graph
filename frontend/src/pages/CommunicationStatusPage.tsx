import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { OutboundDraft } from "../types";

type Step = {
  label: string;
  status: "complete" | "pending" | "attention";
  detail: string;
};

function timeline(draft: OutboundDraft): Step[] {
  const send = draft.send_attempts?.at(-1);
  const move = draft.move_attempts?.at(-1);
  const activeApproval = draft.approvals
    ?.filter((item) => !item.invalidated_at)
    .at(-1);
  const accepted = Boolean(send?.accepted_at || send?.status === "ACCEPTED");
  const sentVerified = Boolean(
    send?.sent_copy_verified_at || send?.status === "SENT_COPY_VERIFIED",
  );
  return [
    {
      label: "Local draft created",
      status: draft.created_at ? "complete" : "pending",
      detail: `Revision ${draft.local_revision}`,
    },
    {
      label: "Graph draft created",
      status: draft.graph_draft_message_id ? "complete" : "pending",
      detail: draft.graph_draft_message_id
        ? "Immutable Graph identity retained"
        : "Not created",
    },
    {
      label: "Exact snapshot approved",
      status: activeApproval?.decision === "APPROVED" ? "complete" : "pending",
      detail: activeApproval
        ? `${activeApproval.decision} by ${activeApproval.approver_actor}`
        : "Separate Sender approval pending",
    },
    {
      label: "Send queued",
      status: draft.send_queued_at ? "complete" : "pending",
      detail: draft.send_queued_at
        ? new Date(draft.send_queued_at).toLocaleString()
        : "Not queued",
    },
    {
      label: "Graph send accepted",
      status:
        draft.draft_status === "SEND_AMBIGUOUS"
          ? "attention"
          : accepted
            ? "complete"
            : "pending",
      detail:
        draft.draft_status === "SEND_AMBIGUOUS"
          ? "Outcome ambiguous; reconciliation only, no automatic resend"
          : accepted
            ? "HTTP 202 accepted for asynchronous processing"
            : "No accepted send request recorded",
    },
    {
      label: "Sent copy verified",
      status: sentVerified ? "complete" : "pending",
      detail: sentVerified
        ? "Matching immutable copy found in shared Sent Items"
        : "Sent Items verification pending",
    },
    {
      label: "Delivery status",
      status:
        draft.delivery_status === "NDR_RECEIVED" ? "attention" : "pending",
      detail:
        draft.delivery_status === "DELIVERY_CONFIRMED"
          ? "Delivery independently confirmed"
          : draft.delivery_status === "NDR_RECEIVED"
            ? "Non-delivery report received"
            : "Delivery is not confirmed; acceptance and Sent Items are not delivery",
    },
    {
      label: "Source message moved",
      status:
        move?.status === "VERIFIED"
          ? "complete"
          : move?.status === "AMBIGUOUS"
            ? "attention"
            : "pending",
      detail: move
        ? `${move.status} · ${move.destination_folder_name}`
        : "Blocked until communication prerequisites are verified",
    },
    {
      label: "Email workflow completed",
      status: draft.completion ? "complete" : "pending",
      detail: draft.completion
        ? `Routing completed; licensing task remained ${draft.completion.task_status_at_completion}`
        : "Email intake/routing remains open",
    },
  ];
}

export function CommunicationStatusPage() {
  const drafts = useQuery({
    queryKey: ["communication-status"],
    queryFn: () => api<OutboundDraft[]>("/outbound-drafts"),
    refetchInterval: 15_000,
  });
  const dashboard = useQuery({
    queryKey: ["communication-dashboard"],
    queryFn: () => api<Record<string, number>>("/communications/dashboard"),
    refetchInterval: 15_000,
  });
  if (drafts.isLoading || dashboard.isLoading) return <Loading />;
  if (drafts.error || dashboard.error)
    return <ErrorState error={drafts.error ?? dashboard.error} />;
  return (
    <main>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Accepted is not delivered</span>
          <h1>Communication status</h1>
          <p>
            Queueing, Graph acceptance, sent-copy verification, delivery, source
            routing, and workflow completion are separate facts.
          </p>
        </div>
      </div>
      <div className="metrics">
        <div>
          <strong>{dashboard.data?.pending_send_approval ?? 0}</strong>
          <span>Pending approval</span>
        </div>
        <div>
          <strong>{dashboard.data?.send_ambiguous ?? 0}</strong>
          <span>Ambiguous sends</span>
        </div>
        <div>
          <strong>{dashboard.data?.workflows_completed ?? 0}</strong>
          <span>Routed email workflows</span>
        </div>
      </div>
      <div className="communication-status-list">
        {drafts.data?.map((draft) => (
          <section className="panel" key={draft.id}>
            <div className="panel-title">
              <div>
                <span className="eyebrow">
                  {draft.task?.title ?? `Task ${draft.task_id}`}
                </span>
                <h2>{draft.subject}</h2>
              </div>
              <div>
                <Status value={draft.draft_status} />{" "}
                <Status value={draft.delivery_status} />
              </div>
            </div>
            <div className="status-steps">
              {timeline(draft).map((step) => (
                <div className={`status-step ${step.status}`} key={step.label}>
                  <span aria-hidden />
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                  </div>
                </div>
              ))}
            </div>
            <Link to={`/communications/drafts/${draft.id}`}>
              Open controlled history →
            </Link>
          </section>
        ))}
        {drafts.data?.length === 0 && (
          <div className="empty-state">
            <h2>No communication history</h2>
            <p>Controlled drafts will appear here.</p>
          </div>
        )}
      </div>
    </main>
  );
}
