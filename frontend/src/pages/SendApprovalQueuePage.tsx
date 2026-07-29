import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { Actor, OutboundDraft } from "../types";

function expectation(draft: OutboundDraft) {
  return {
    expected_revision: draft.local_revision,
    expected_graph_change_key: draft.graph_change_key,
    expected_graph_etag: draft.graph_etag,
  };
}

export function SendApprovalQueuePage() {
  const qc = useQueryClient();
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState<Record<string, string>>({});
  const [queued, setQueued] = useState<Record<string, boolean>>({});
  const actor = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Actor>("/auth/me"),
  });
  const q = useQuery({
    queryKey: ["send-approval-queue"],
    queryFn: () =>
      api<OutboundDraft[]>("/outbound-drafts").then((rows) =>
        rows.filter((row) =>
          ["PENDING_SEND_APPROVAL", "APPROVED_TO_SEND", "SEND_QUEUED"].includes(
            row.draft_status,
          ),
        ),
      ),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["send-approval-queue"] });
    void qc.invalidateQueries({ queryKey: ["outbound-drafts"] });
  };
  const approve = useMutation({
    mutationFn: (draft: OutboundDraft) =>
      api(`/outbound-drafts/${draft.id}/approve-send`, {
        method: "POST",
        body: JSON.stringify({
          expected_revision: draft.local_revision,
          expected_approval_snapshot_sha256:
            draft.pending_approval_snapshot_sha256,
          expected_graph_draft_id: draft.graph_draft_message_id,
          expected_graph_change_key: draft.graph_change_key,
          expected_graph_etag: draft.graph_etag,
          approval_notes: reason[draft.id] || null,
        }),
      }),
    onSuccess: refresh,
  });
  const reviewDecision = useMutation({
    mutationFn: ({
      draft,
      operation,
    }: {
      draft: OutboundDraft;
      operation: "send-request-changes" | "reject-send" | "cancel-send";
    }) =>
      api(`/outbound-drafts/${draft.id}/${operation}`, {
        method: "POST",
        body: JSON.stringify({
          ...expectation(draft),
          reason: reason[draft.id],
        }),
      }),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: (draft: OutboundDraft) =>
      api(`/outbound-drafts/${draft.id}/send`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          explicit_confirmation: true,
        }),
      }),
    onSuccess: (_result, draft) => {
      setQueued((value) => ({ ...value, [draft.id]: true }));
      refresh();
    },
  });
  if (q.isLoading || actor.isLoading) return <Loading />;
  if (q.error || actor.error)
    return <ErrorState error={q.error ?? actor.error} />;
  const error = approve.error ?? reviewDecision.error ?? send.error;
  return (
    <main>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Independent Sender control</span>
          <h1>Send approval</h1>
          <p>
            Classification review is not send approval. A Sender reviews the
            exact Graph-backed snapshot and separately confirms queueing.
          </p>
        </div>
      </div>
      <div className="approval-grid">
        {q.data?.map((draft) => {
          const activeApprovals = draft.approvals?.filter(
            (item) => !item.invalidated_at,
          );
          const selfApproval =
            actor.data?.user_id === draft.created_by_actor ||
            actor.data?.user_id === draft.last_edited_by_actor ||
            activeApprovals?.some(
              (item) =>
                item.decision === "PENDING_SECOND_APPROVAL" &&
                item.approver_actor === actor.data?.user_id,
            );
          return (
            <section className="panel approval-card" key={draft.id}>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">
                    {draft.task?.title ?? `Task ${draft.task_id}`}
                  </span>
                  <h2>{draft.subject}</h2>
                </div>
                <Status value={draft.draft_status} />
              </div>
              <div className="approval-facts">
                <div>
                  <small>Sender mailbox</small>
                  <strong>{draft.sender_mailbox ?? "Not configured"}</strong>
                </div>
                <div>
                  <small>Task state</small>
                  <strong>{draft.task?.status ?? "Unknown"}</strong>
                </div>
                <div>
                  <small>Response plan</small>
                  <strong>
                    {draft.response_plan?.response_type.replaceAll("_", " ")}
                  </strong>
                </div>
                <div>
                  <small>Last reviewer / editor</small>
                  <strong>{draft.last_edited_by_actor ?? "System"}</strong>
                </div>
              </div>
              <h3>Exact recipients</h3>
              <dl className="recipient-review">
                <div>
                  <dt>To</dt>
                  <dd>
                    {draft.to_recipients
                      .map((recipient) => recipient.address)
                      .join(", ")}
                  </dd>
                </div>
                <div>
                  <dt>CC</dt>
                  <dd>
                    {draft.cc_recipients
                      .map((recipient) => recipient.address)
                      .join(", ") || "None"}
                  </dd>
                </div>
                <div>
                  <dt>BCC</dt>
                  <dd>
                    {draft.bcc_recipients
                      .map((recipient) => recipient.address)
                      .join(", ") || "None"}
                  </dd>
                </div>
              </dl>
              {draft.external_recipient_domains?.length ? (
                <div className="warning-box">
                  External recipient domains:{" "}
                  {draft.external_recipient_domains.join(", ")}
                </div>
              ) : null}
              <h3>Full response</h3>
              <pre className="draft-preview">
                {draft.body_text ?? draft.body_html}
              </pre>
              <h3>Controlled attachment set</h3>
              {draft.attachments.length ? (
                draft.attachments.map((attachment) => (
                  <div className="attachment-review" key={attachment.id}>
                    <strong>{attachment.filename}</strong>
                    <span>
                      {attachment.document_approval_status} ·{" "}
                      {attachment.document_lifecycle_status} ·{" "}
                      {attachment.document_storage_status} ·{" "}
                      <Status value={attachment.status} />
                    </span>
                  </div>
                ))
              ) : (
                <p>None</p>
              )}
              <h3>Snapshot and warnings</h3>
              <code className="snapshot-hash">
                {draft.pending_approval_snapshot_sha256}
              </code>
              <p>
                Revision {draft.local_revision} · Graph ID retained ·{" "}
                {draft.validation_findings?.length
                  ? draft.validation_findings.join(", ")
                  : "No current validation findings"}
              </p>
              {activeApprovals?.map((approval) => (
                <p key={approval.id}>
                  <Status value={approval.decision} /> by{" "}
                  {approval.approver_actor} at{" "}
                  {new Date(
                    approval.approved_at ?? approval.created_at,
                  ).toLocaleString()}
                </p>
              ))}
              <label>
                Approval / review note
                <textarea
                  rows={2}
                  value={reason[draft.id] ?? ""}
                  onChange={(event) =>
                    setReason((value) => ({
                      ...value,
                      [draft.id]: event.target.value,
                    }))
                  }
                />
              </label>
              {draft.draft_status === "PENDING_SEND_APPROVAL" && (
                <div className="decision-actions">
                  <button
                    className="approve"
                    disabled={approve.isPending || selfApproval}
                    onClick={() => approve.mutate(draft)}
                  >
                    Approve exact snapshot
                  </button>
                  <button
                    className="secondary"
                    disabled={
                      reviewDecision.isPending ||
                      (reason[draft.id]?.trim().length ?? 0) < 2
                    }
                    onClick={() =>
                      reviewDecision.mutate({
                        draft,
                        operation: "send-request-changes",
                      })
                    }
                  >
                    Request changes
                  </button>
                  <button
                    className="danger-button"
                    disabled={
                      reviewDecision.isPending ||
                      (reason[draft.id]?.trim().length ?? 0) < 2
                    }
                    onClick={() =>
                      reviewDecision.mutate({ draft, operation: "reject-send" })
                    }
                  >
                    Reject
                  </button>
                </div>
              )}
              {selfApproval &&
                draft.draft_status === "PENDING_SEND_APPROVAL" && (
                  <p className="warning-text">
                    Separation of duties blocks this user from approving their
                    own revision.
                  </p>
                )}
              {draft.draft_status === "APPROVED_TO_SEND" && (
                <div className="send-confirmation">
                  <h3>Independent send confirmation</h3>
                  <ul>
                    <li>Mailbox: {draft.sender_mailbox}</li>
                    <li>
                      Recipients:{" "}
                      {draft.to_recipients.length +
                        draft.cc_recipients.length +
                        draft.bcc_recipients.length}
                    </li>
                    <li>
                      External domains:{" "}
                      {draft.external_recipient_domains?.join(", ") || "None"}
                    </li>
                    <li>Subject: {draft.subject}</li>
                    <li>Attachments: {draft.attachments.length}</li>
                    <li>
                      Approved:{" "}
                      {draft.approved_at
                        ? new Date(draft.approved_at).toLocaleString()
                        : "Recorded in active snapshot"}
                    </li>
                  </ul>
                  <label>
                    <input
                      type="checkbox"
                      checked={confirmed[draft.id] ?? false}
                      onChange={(event) =>
                        setConfirmed((value) => ({
                          ...value,
                          [draft.id]: event.target.checked,
                        }))
                      }
                    />{" "}
                    I independently verified every value above and intend to
                    queue this approved snapshot.
                  </label>
                  <button
                    disabled={!confirmed[draft.id] || send.isPending}
                    onClick={() => send.mutate(draft)}
                  >
                    Queue approved send
                  </button>
                  <button
                    className="danger-button"
                    disabled={
                      reviewDecision.isPending ||
                      (reason[draft.id]?.trim().length ?? 0) < 2
                    }
                    onClick={() =>
                      reviewDecision.mutate({
                        draft,
                        operation: "cancel-send",
                      })
                    }
                  >
                    Cancel approved draft
                  </button>
                </div>
              )}
              {(draft.draft_status === "SEND_QUEUED" || queued[draft.id]) && (
                <div className="success-box">
                  Send was queued for the durable worker. No delivery claim is
                  made.
                  {draft.draft_status === "SEND_QUEUED" && (
                    <button
                      className="danger-button"
                      disabled={
                        reviewDecision.isPending ||
                        (reason[draft.id]?.trim().length ?? 0) < 2
                      }
                      onClick={() =>
                        reviewDecision.mutate({
                          draft,
                          operation: "cancel-send",
                        })
                      }
                    >
                      Cancel if worker has not started
                    </button>
                  )}
                </div>
              )}
            </section>
          );
        })}
        {q.data?.length === 0 && (
          <div className="empty-state">
            <h2>No drafts awaiting Sender action</h2>
            <p>Submitted exact snapshots will appear here.</p>
          </div>
        )}
      </div>
      {error && <ErrorState error={error} />}
    </main>
  );
}
