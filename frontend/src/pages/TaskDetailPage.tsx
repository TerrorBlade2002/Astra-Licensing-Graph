import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type {
  CommunicationTemplate,
  OutboundDraft,
  ResponsePlan,
  Task,
} from "../types";

const responseTypes = [
  "ACKNOWLEDGEMENT",
  "INFORMATION_RESPONSE",
  "DOCUMENT_RESPONSE",
  "CLARIFICATION_RESPONSE",
  "PAYMENT_CONFIRMATION",
  "FILING_CONFIRMATION",
  "REGULATOR_RESPONSE",
  "BOND_RESPONSE",
  "INTERNAL_FORWARD",
  "NO_RESPONSE_REQUIRED",
];

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [owner, setOwner] = useState("");
  const [responseType, setResponseType] = useState("ACKNOWLEDGEMENT");
  const [recipientMode, setRecipientMode] = useState("REPLY");
  const q = useQuery({
    queryKey: ["task", id],
    queryFn: () => api<Task>(`/licensing-tasks/${id}`),
  });
  const templates = useQuery({
    queryKey: ["communication-templates"],
    queryFn: () => api<CommunicationTemplate[]>("/communication-templates"),
  });
  const plan = useQuery({
    queryKey: ["response-plan", id],
    queryFn: () => api<ResponsePlan>(`/licensing-tasks/${id}/response-plan`),
    retry: false,
  });
  const drafts = useQuery({
    queryKey: ["task-communications", id],
    queryFn: () =>
      api<OutboundDraft[]>(
        `/outbound-drafts?task_id=${encodeURIComponent(id)}`,
      ),
  });
  const createPlan = useMutation({
    mutationFn: () => {
      const template = templates.data?.find(
        (item) => item.response_type === responseType && item.active_version_id,
      );
      return api<ResponsePlan>(`/licensing-tasks/${id}/response-plan`, {
        method: "POST",
        body: JSON.stringify({
          response_type: responseType,
          recipient_mode:
            responseType === "NO_RESPONSE_REQUIRED" ? "NONE" : recipientMode,
          template_version_id: template?.active_version_id,
        }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["response-plan", id] });
      void qc.invalidateQueries({ queryKey: ["task-communications", id] });
      void qc.invalidateQueries({ queryKey: ["task", id] });
    },
  });
  const generateDraft = useMutation({
    mutationFn: () =>
      api<OutboundDraft>(`/response-plans/${plan.data!.id}/drafts`, {
        method: "POST",
        body: JSON.stringify({ values: {} }),
      }),
    onSuccess: (draft) => navigate(`/communications/drafts/${draft.id}`),
  });
  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body: object }) =>
      api<Task>(`/licensing-tasks/${id}${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["task", id] }),
  });
  const updateItem = useMutation({
    mutationFn: (item: NonNullable<Task["requested_items"]>[number]) =>
      api(`/licensing-tasks/${id}/requested-items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          item_text: item.item_text,
          category: item.category,
          required: item.required,
          evidence_quote: item.evidence_quote,
          status: "VERIFIED",
          owner: item.owner,
        }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["task", id] }),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const task = q.data!;
  const communication = drafts.data?.at(0);
  const mutationError =
    createPlan.error ?? generateDraft.error ?? mutate.error ?? updateItem.error;
  return (
    <main>
      <div className="review-header">
        <button className="back" onClick={() => navigate("/tasks")}>
          ← Board
        </button>
        <div>
          <span className="eyebrow">{task.queue.replaceAll("_", " ")}</span>
          <h1>{task.title}</h1>
        </div>
        <Status value={task.status} />
      </div>
      <div className="task-detail-grid">
        <section className="panel">
          <h2>Work details</h2>
          <dl className="detail-list">
            <div>
              <dt>Owner</dt>
              <dd>{task.assigned_to ?? "Unassigned"}</dd>
            </div>
            <div>
              <dt>Due date</dt>
              <dd>{task.due_date ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>{task.priority}</dd>
            </div>
            <div>
              <dt>Draft posture</dt>
              <dd>{task.draft_status} · no implicit send</dd>
            </div>
          </dl>
          <div className="assign-row">
            <input
              aria-label="Owner"
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              placeholder="owner@astra.example"
            />
            <button
              className="secondary"
              onClick={() =>
                mutate.mutate({
                  path: "/assign",
                  body: { assigned_to: owner },
                })
              }
            >
              Assign
            </button>
          </div>
          <div className="transition-row">
            {[
              "IN_REVIEW",
              "WAITING_FOR_INFO",
              "READY_TO_SEND",
              "COMPLETED",
            ].map((status) => (
              <button
                key={status}
                onClick={() =>
                  mutate.mutate({
                    path: "/transition",
                    body: { status },
                  })
                }
              >
                {status.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>Requested information</h2>
          <div className="checklist">
            {task.requested_items?.map((item) => (
              <div key={item.id}>
                <span
                  className={`check ${item.status !== "OPEN" ? "done" : ""}`}
                />
                <div>
                  <strong>{item.item_text}</strong>
                  <p>{item.evidence_quote}</p>
                </div>
                {item.status === "OPEN" ? (
                  <button
                    className="text-button"
                    aria-label={`Mark ${item.item_text} verified`}
                    onClick={() => updateItem.mutate(item)}
                  >
                    Mark verified
                  </button>
                ) : (
                  <Status value={item.status} />
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>Controlled communication plan</h2>
          {plan.data ? (
            <>
              <p>
                {plan.data.response_type.replaceAll("_", " ")} ·{" "}
                <Status value={plan.data.readiness_status} />
              </p>
              <dl className="detail-list">
                <div>
                  <dt>Recipient mode</dt>
                  <dd>{plan.data.recipient_mode}</dd>
                </div>
                <div>
                  <dt>Destination</dt>
                  <dd>{plan.data.destination_folder_name ?? "Not verified"}</dd>
                </div>
                <div>
                  <dt>Readiness blockers</dt>
                  <dd>{plan.data.readiness_blockers.join(", ") || "None"}</dd>
                </div>
              </dl>
              {plan.data.response_required && !communication && (
                <button
                  onClick={() => generateDraft.mutate()}
                  disabled={!plan.data.selected_template_version_id}
                >
                  Generate reviewable draft
                </button>
              )}
              {!plan.data.response_required && (
                <p>
                  No email will be drafted or sent. Source routing runs as a
                  separate durable workflow.
                </p>
              )}
            </>
          ) : (
            <div className="response-plan-form">
              <label>
                Response type
                <select
                  value={responseType}
                  onChange={(event) => setResponseType(event.target.value)}
                >
                  {responseTypes.map((value) => (
                    <option value={value} key={value}>
                      {value.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
              {responseType !== "NO_RESPONSE_REQUIRED" && (
                <label>
                  Recipient mode
                  <select
                    value={recipientMode}
                    onChange={(event) => setRecipientMode(event.target.value)}
                  >
                    <option value="REPLY">Reply</option>
                    <option value="MANUAL">Manual recipients</option>
                    <option value="INTERNAL_FORWARD">Internal forward</option>
                  </select>
                </label>
              )}
              <button
                onClick={() => createPlan.mutate()}
                disabled={
                  createPlan.isPending ||
                  (responseType !== "NO_RESPONSE_REQUIRED" &&
                    !templates.data?.some(
                      (item) =>
                        item.response_type === responseType &&
                        item.active_version_id,
                    ))
                }
              >
                Create controlled response plan
              </button>
            </div>
          )}
          <p>
            Classification approval never authorizes a send. A separate Sender
            must approve the exact draft snapshot.
          </p>
        </section>

        <section className="panel communication-history">
          <h2>Communication execution</h2>
          {communication ? (
            <>
              <div className="panel-title">
                <div>
                  <strong>{communication.subject}</strong>
                  <small>Revision {communication.local_revision}</small>
                </div>
                <Status value={communication.draft_status} />
              </div>
              <dl className="detail-list">
                <div>
                  <dt>Graph draft</dt>
                  <dd>
                    {communication.graph_draft_message_id
                      ? "Immutable ID retained"
                      : "Not created"}
                  </dd>
                </div>
                <div>
                  <dt>Approvals</dt>
                  <dd>{communication.approvals?.length ?? 0}</dd>
                </div>
                <div>
                  <dt>Latest send attempt</dt>
                  <dd>
                    {communication.send_attempts?.at(-1)?.status ?? "None"}
                  </dd>
                </div>
                <div>
                  <dt>Source move</dt>
                  <dd>
                    {communication.move_attempts?.at(-1)?.status ??
                      "Not started"}
                  </dd>
                </div>
                <div>
                  <dt>Source folder</dt>
                  <dd>
                    {communication.move_attempts?.at(-1)
                      ?.destination_folder_name ??
                      communication.task?.destination_folder_name ??
                      "Not verified"}
                  </dd>
                </div>
                <div>
                  <dt>Email workflow</dt>
                  <dd>
                    {communication.completion?.communication_status ??
                      "Not completed"}
                  </dd>
                </div>
                <div>
                  <dt>Licensing task at routing completion</dt>
                  <dd>
                    {communication.completion?.task_status_at_completion ??
                      task.status}
                  </dd>
                </div>
              </dl>
              <div className="transition-row">
                <Link to={`/communications/drafts/${communication.id}`}>
                  Open draft and revisions →
                </Link>
                <Link to="/communications/status">Open status timeline →</Link>
              </div>
            </>
          ) : (
            <>
              <p>
                {plan.data?.response_required === false
                  ? "No-response routing has no outbound draft."
                  : "No outbound draft has been generated."}
              </p>
              {plan.data?.response_required === false && (
                <dl className="detail-list">
                  <div>
                    <dt>Source move</dt>
                    <dd>
                      {plan.data.move_attempts?.at(-1)?.status ?? "Queued"}
                    </dd>
                  </div>
                  <div>
                    <dt>Source folder</dt>
                    <dd>
                      {plan.data.move_attempts?.at(-1)
                        ?.destination_folder_name ??
                        plan.data.destination_folder_name ??
                        "Not verified"}
                    </dd>
                  </div>
                  <div>
                    <dt>Email workflow</dt>
                    <dd>
                      {plan.data.completion?.communication_status ??
                        task.communication_status ??
                        "Not completed"}
                    </dd>
                  </div>
                  <div>
                    <dt>Licensing task remains</dt>
                    <dd>
                      {plan.data.completion?.task_status_at_completion ??
                        task.status}
                    </dd>
                  </div>
                </dl>
              )}
            </>
          )}
        </section>

        <section className="panel timeline-panel">
          <h2>Activity timeline</h2>
          <div className="timeline">
            {task.events?.map((event) => (
              <div key={event.id}>
                <span />
                <div>
                  <strong>{event.event_type.replaceAll("_", " ")}</strong>
                  <p>
                    {event.actor_id ?? "System"} ·{" "}
                    {new Date(event.occurred_at).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
      {mutationError && <ErrorState error={mutationError} />}
    </main>
  );
}
