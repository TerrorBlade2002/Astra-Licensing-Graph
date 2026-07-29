import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { z } from "zod";
import { api } from "../api/client";
import {
  Confidence,
  ErrorState,
  Loading,
  Status,
} from "../components/common/States";
import type { Classification, Review, ReviewDetail } from "../types";

const schema = z.object({
  vendor: z.string().nullable(),
  email_type: z.string(),
  states: z.array(z.string()),
  license_types: z.array(z.string()),
  license_numbers: z.array(z.string()),
  action_required: z.boolean(),
  requested_information: z.array(
    z.object({
      item: z.string().min(2),
      category: z.string(),
      required: z.boolean(),
      evidence_quote: z.string().min(2),
    }),
  ),
  documents: z.array(
    z.object({
      filename: z.string(),
      document_type: z.string(),
      relationship: z.string(),
    }),
  ),
  due_date: z.string().nullable(),
  summary: z.string(),
  proposed_action: z.string(),
  suggested_destination: z.string(),
  confidence: z.number(),
  requires_human_review: z.boolean(),
  review_reasons: z.array(z.string()),
});
export function ClassificationReviewPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["review", id],
    queryFn: () => api<ReviewDetail>(`/classification-reviews/${id}`),
  });
  const form = useForm<Classification>({
    resolver: zodResolver(schema),
    values: q.data?.classification,
  });
  const fields = useFieldArray({
    control: form.control,
    name: "requested_information",
  });
  const decision = useMutation({
    mutationFn: ({ action, body }: { action: string; body: object }) =>
      api<Review>(`/classification-reviews/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["review", id] }),
  });
  const create = useMutation({
    mutationFn: (reviewId: string) =>
      api<{ id: string }>(`/classification-reviews/${reviewId}/create-task`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: (data) => void navigate(`/tasks/${data.id}`),
  });
  if (q.isLoading) return <Loading label="Assembling evidence" />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data!;
  const rev = d.review;
  const mutate = (action: string, extra: object = {}) =>
    decision.mutate({
      action,
      body: { expected_revision: rev.revision, ...extra },
    });
  return (
    <main className="review-page">
      <div className="review-header">
        <button className="back" onClick={() => navigate("/reviews")}>
          ← Queue
        </button>
        <div>
          <span className="eyebrow">
            Review {d.classification_version} ·{" "}
            {d.classification.vendor ?? "Unknown vendor"}
          </span>
          <h1>{d.subject ?? "No subject"}</h1>
        </div>
        <div className="review-meta">
          <Status value={rev.decision} />
          <Confidence value={d.classification.confidence} />
        </div>
      </div>
      <div className="review-grid">
        <section className="evidence-pane">
          <div className="pane-heading">
            <span>Source evidence</span>
            <small>{d.sender}</small>
          </div>
          <dl className="mail-meta">
            <div>
              <dt>Received</dt>
              <dd>
                {d.received_at ? new Date(d.received_at).toLocaleString() : "—"}
              </dd>
            </div>
            <div>
              <dt>Attachments</dt>
              <dd>{d.has_attachments ? "Present" : "None"}</dd>
            </div>
          </dl>
          <article className="email-body">
            {d.current_message_body || "No normalized message body was stored."}
          </article>
          {d.quoted_history && (
            <details>
              <summary>Quoted conversation history</summary>
              <pre>{d.quoted_history}</pre>
            </details>
          )}
        </section>
        <section className="machine-pane">
          <div className="pane-heading">
            <span>Machine proposal</span>
            <small>Version {d.classification_version}</small>
          </div>
          <div className="classification-card">
            <span className="eyebrow">Proposed type</span>
            <h2>{d.classification.email_type.replaceAll("_", " ")}</h2>
            <p>{d.classification.summary}</p>
          </div>
          <div className="fact-grid">
            <div>
              <small>Vendor</small>
              <strong>{d.classification.vendor ?? "Unresolved"}</strong>
            </div>
            <div>
              <small>Jurisdiction</small>
              <strong>
                {d.classification.states.join(", ") || "Unresolved"}
              </strong>
            </div>
            <div>
              <small>License</small>
              <strong>
                {d.classification.license_types.join(", ") || "Unresolved"}
              </strong>
            </div>
            <div>
              <small>Route</small>
              <strong>{d.classification.suggested_destination}</strong>
            </div>
          </div>
          <h3>Rule evidence</h3>
          <div className="evidence-list">
            {d.rule_evidence.map((e, i) => (
              <div key={i}>
                <span>{String(e.rule_id ?? "rule")}</span>
                <p>{String(e.matched_text ?? "")}</p>
              </div>
            ))}
          </div>
          <h3>Review reasons</h3>
          <ul>
            {d.classification.review_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </section>
        <form
          className="decision-pane"
          onSubmit={form.handleSubmit((values) =>
            decision.mutate({
              action: "correct",
              body: {
                expected_revision: rev.revision,
                classification: values,
                correction_reasons: {
                  requested_information:
                    "Reviewer corrected requested information",
                },
                notes: "Evidence-aligned correction",
              },
            }),
          )}
        >
          <div className="pane-heading">
            <span>Human decision</span>
            <small>Revision {rev.revision}</small>
          </div>
          <label>
            Email type
            <input {...form.register("email_type")} />
          </label>
          <div className="form-row">
            <label>
              Due date
              <input type="date" {...form.register("due_date")} />
            </label>
            <label>
              Route
              <input {...form.register("suggested_destination")} />
            </label>
          </div>
          <label>
            Summary
            <textarea rows={3} {...form.register("summary")} />
          </label>
          <div className="items-heading">
            <h3>Requested information</h3>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                fields.append({
                  item: "",
                  category: "unknown",
                  required: true,
                  evidence_quote: "",
                })
              }
            >
              + Add
            </button>
          </div>
          {fields.fields.map((field, index) => (
            <fieldset className="request-item" key={field.id}>
              <button
                type="button"
                aria-label={`Remove item ${index + 1}`}
                onClick={() => fields.remove(index)}
              >
                ×
              </button>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <label>
                Requested item
                <input
                  {...form.register(`requested_information.${index}.item`)}
                />
              </label>
              <label>
                Evidence quote
                <textarea
                  rows={2}
                  {...form.register(
                    `requested_information.${index}.evidence_quote`,
                  )}
                />
              </label>
            </fieldset>
          ))}
          {decision.error && <ErrorState error={decision.error} />}
          <div className="decision-actions">
            {rev.decision === "PENDING" && (
              <button
                type="button"
                className="secondary"
                onClick={() => mutate("claim")}
              >
                Claim review
              </button>
            )}
            <button
              type="button"
              className="approve"
              onClick={() => mutate("approve")}
            >
              Approve as proposed
            </button>
            <button type="submit" className="primary">
              Save correction
            </button>
            <button
              type="button"
              className="danger-link"
              onClick={() =>
                mutate("reject", {
                  reason: "Evidence does not support this classification",
                })
              }
            >
              Reject
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                mutate("request-reclassification", {
                  reason: "Run against updated evidence or rules",
                })
              }
            >
              Request reclassification
            </button>
            {["APPROVED", "CORRECTED"].includes(rev.decision) && (
              <button
                type="button"
                className="create-task"
                onClick={() => create.mutate(rev.id)}
              >
                Create licensing task →
              </button>
            )}
          </div>
        </form>
      </div>
    </main>
  );
}
