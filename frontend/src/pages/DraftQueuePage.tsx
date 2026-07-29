import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { OutboundDraft } from "../types";

export function DraftQueuePage() {
  const q = useQuery({
    queryKey: ["outbound-drafts"],
    queryFn: () => api<OutboundDraft[]>("/outbound-drafts"),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <main>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Controlled communications</span>
          <h1>Draft queue</h1>
          <p>
            Every revision stays reviewable until a separate Sender approves its
            exact Graph-backed snapshot.
          </p>
        </div>
      </div>
      <section className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>Task / source</th>
              <th>Response</th>
              <th>Status</th>
              <th>Recipient</th>
              <th>Owner / due</th>
              <th>Editor / approver</th>
              <th>Attachments</th>
              <th>Blockers</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data?.map((draft) => {
              const validApproval = draft.approvals
                ?.filter((item) => !item.invalidated_at)
                .at(-1);
              return (
                <tr key={draft.id}>
                  <td>
                    <strong>
                      {draft.task?.title ?? `Task ${draft.task_id}`}
                    </strong>
                    <small>
                      {draft.source_email?.subject ?? draft.subject}
                    </small>
                  </td>
                  <td>
                    {draft.response_plan?.response_type.replaceAll("_", " ") ??
                      "Not set"}
                    <small>Revision {draft.local_revision}</small>
                  </td>
                  <td>
                    <Status value={draft.draft_status} />
                  </td>
                  <td>
                    {draft.to_recipients
                      .map((recipient) => recipient.address)
                      .join(", ") || "Graph reply recipient pending"}
                  </td>
                  <td>
                    {draft.task?.owner ?? "Unassigned"}
                    <small>{draft.task?.due_date ?? "No due date"}</small>
                  </td>
                  <td>
                    {draft.last_edited_by_actor ?? "System"}
                    <small>
                      {validApproval
                        ? `Approver ${validApproval.approver_actor}`
                        : "No active send approval"}
                    </small>
                  </td>
                  <td>{draft.attachments.length}</td>
                  <td>
                    {draft.validation_findings?.length ? (
                      <span className="warning-text">
                        {draft.validation_findings.join(", ")}
                      </span>
                    ) : (
                      "None"
                    )}
                  </td>
                  <td>
                    <Link to={`/communications/drafts/${draft.id}`}>
                      Open →
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {q.data?.length === 0 && (
          <div className="empty-state">
            <h2>No controlled drafts</h2>
            <p>Create a response plan from a licensing task.</p>
          </div>
        )}
      </section>
    </main>
  );
}
