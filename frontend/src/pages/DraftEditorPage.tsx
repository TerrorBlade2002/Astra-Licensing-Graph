import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { ControlledDocument, DraftVersion, OutboundDraft } from "../types";

function recipients(value: string) {
  return value
    .split(",")
    .map((address) => ({ address: address.trim(), name: "" }))
    .filter((recipient) => recipient.address);
}

function expectation(draft: OutboundDraft) {
  return {
    expected_revision: draft.local_revision,
    expected_graph_change_key: draft.graph_change_key,
    expected_graph_etag: draft.graph_etag,
  };
}

function AddedLines({ baseline, value }: { baseline: string; value: string }) {
  const known = new Set(baseline.split(/\r?\n/).map((line) => line.trim()));
  return (
    <pre className="diff-text">
      {value.split(/\r?\n/).map((line, index) => {
        const added = line.trim() && !known.has(line.trim());
        return (
          <span className={added ? "diff-added" : ""} key={`${index}-${line}`}>
            {line || " "}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}

function DraftDiff({ versions }: { versions: DraftVersion[] }) {
  const ordered = useMemo(
    () => [...versions].sort((a, b) => a.revision - b.revision),
    [versions],
  );
  const [baseRevision, setBaseRevision] = useState<number>();
  const [compareRevision, setCompareRevision] = useState<number>();
  useEffect(() => {
    if (!ordered.length) return;
    setBaseRevision((value) => value ?? ordered[0]!.revision);
    setCompareRevision((value) => value ?? ordered.at(-1)!.revision);
  }, [ordered]);
  const baseline =
    ordered.find((version) => version.revision === baseRevision) ?? ordered[0];
  const compared =
    ordered.find((version) => version.revision === compareRevision) ??
    ordered.at(-1);
  if (!baseline || !compared) return <p>No revision history yet.</p>;
  const baseRecipients = [
    ...baseline.to_recipients,
    ...baseline.cc_recipients,
    ...baseline.bcc_recipients,
  ].map((item) => item.address);
  const comparedRecipients = [
    ...compared.to_recipients,
    ...compared.cc_recipients,
    ...compared.bcc_recipients,
  ].map((item) => item.address);
  return (
    <div className="draft-diff">
      <div className="diff-toolbar">
        <label>
          Baseline
          <select
            value={baseline.revision}
            onChange={(event) => setBaseRevision(Number(event.target.value))}
          >
            {ordered.map((version) => (
              <option value={version.revision} key={version.id}>
                r{version.revision} · {version.change_reason ?? "revision"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Compare
          <select
            value={compared.revision}
            onChange={(event) => setCompareRevision(Number(event.target.value))}
          >
            {ordered.map((version) => (
              <option value={version.revision} key={version.id}>
                r{version.revision} · {version.change_reason ?? "revision"}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="diff-grid">
        <div>
          <span className="eyebrow">Machine / earlier snapshot</span>
          <strong>{baseline.subject}</strong>
          <pre className="diff-text">
            {baseline.body_text ?? baseline.body_html}
          </pre>
          <small>{baseRecipients.join(", ") || "No recipients"}</small>
        </div>
        <div>
          <span className="eyebrow">Reviewer / Graph / latest snapshot</span>
          <strong
            className={
              baseline.subject !== compared.subject ? "diff-added" : ""
            }
          >
            {compared.subject}
          </strong>
          <AddedLines
            baseline={baseline.body_text ?? baseline.body_html ?? ""}
            value={compared.body_text ?? compared.body_html ?? ""}
          />
          <small>
            {comparedRecipients.map((recipient) => (
              <mark
                className={
                  baseRecipients.includes(recipient) ? "" : "diff-added"
                }
                key={recipient}
              >
                {recipient}
              </mark>
            ))}
          </small>
        </div>
      </div>
      <div className="diff-manifest">
        Attachments: {baseline.attachment_manifest.length} →{" "}
        {compared.attachment_manifest.length}
        {compared.attachment_manifest.map((item) => (
          <span
            className={
              baseline.attachment_manifest.some((prior) => prior.id === item.id)
                ? ""
                : "diff-added"
            }
            key={item.id}
          >
            {item.filename}
          </span>
        ))}
      </div>
    </div>
  );
}

export function DraftEditorPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["outbound-draft", id],
    queryFn: () => api<OutboundDraft>(`/outbound-drafts/${id}`),
  });
  const history = useQuery({
    queryKey: ["outbound-draft-versions", id],
    queryFn: () => api<DraftVersion[]>(`/outbound-drafts/${id}/versions`),
  });
  const documents = useQuery({
    queryKey: ["approved-communication-documents"],
    queryFn: () =>
      api<{ items: ControlledDocument[] }>(
        "/documents?approval_status=APPROVED&lifecycle_status=ACTIVE&approved_for_reuse=true&page_size=100",
      ),
  });
  const capabilities = useQuery({
    queryKey: ["communication-capabilities"],
    queryFn: () =>
      api<{
        response_ai_drafting_enabled: boolean;
        attachments_enabled: boolean;
        large_attachments_enabled: boolean;
      }>("/communications/capabilities"),
  });
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [changeReason, setChangeReason] = useState("Portal reviewer edit");
  useEffect(() => {
    if (!q.data) return;
    setSubject(q.data.subject);
    setBody(q.data.body_text ?? "");
    setTo(q.data.to_recipients.map((item) => item.address).join(", "));
    setCc(q.data.cc_recipients.map((item) => item.address).join(", "));
  }, [q.data]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["outbound-draft", id] });
    void qc.invalidateQueries({ queryKey: ["outbound-draft-versions", id] });
    void qc.invalidateQueries({ queryKey: ["outbound-drafts"] });
  };
  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) =>
      api(`/outbound-drafts/${id}${path}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      }),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: () =>
      api(`/outbound-drafts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...expectation(q.data!),
          subject,
          body_text: body,
          body_html: null,
          to_recipients: recipients(to),
          cc_recipients: recipients(cc),
          bcc_recipients: q.data!.bcc_recipients,
          change_reason: changeReason,
        }),
      }),
    onSuccess: refresh,
  });
  const attach = useMutation({
    mutationFn: (document: ControlledDocument) =>
      api(`/outbound-drafts/${id}/attachments`, {
        method: "POST",
        body: JSON.stringify({
          ...expectation(q.data!),
          document_id: document.id,
          document_version_id: document.current_version_id,
        }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (attachmentId: string) => {
      const draft = q.data!;
      const params = new URLSearchParams({
        expected_revision: String(draft.local_revision),
      });
      if (draft.graph_change_key)
        params.set("expected_graph_change_key", draft.graph_change_key);
      if (draft.graph_etag) params.set("expected_graph_etag", draft.graph_etag);
      return api(
        `/outbound-drafts/${id}/attachments/${attachmentId}?${params}`,
        { method: "DELETE" },
      );
    },
    onSuccess: refresh,
  });
  const selectedDocumentIds = useMemo(
    () => new Set(q.data?.attachments.map((item) => item.document_id)),
    [q.data],
  );

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const draft = q.data!;
  const busy =
    action.isPending || save.isPending || attach.isPending || remove.isPending;
  const error = action.error ?? save.error ?? attach.error ?? remove.error;
  const mayEdit = ![
    "SEND_QUEUED",
    "SENDING",
    "SEND_ACCEPTED",
    "SEND_AMBIGUOUS",
    "SENT_COPY_VERIFIED",
    "CANCELLED",
  ].includes(draft.draft_status);
  return (
    <main className="draft-editor-page">
      <div className="review-header">
        <div>
          <span className="eyebrow">Draft editor · exact revision control</span>
          <h1>{draft.subject}</h1>
        </div>
        <Status value={draft.draft_status} />
      </div>
      <div className="draft-editor-grid">
        <aside className="panel draft-context">
          <h2>Source, review & task</h2>
          <dl className="detail-list">
            <div>
              <dt>Task</dt>
              <dd>{draft.task?.title ?? draft.task_id}</dd>
            </div>
            <div>
              <dt>Task state</dt>
              <dd>{draft.task?.status ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Response</dt>
              <dd>{draft.response_plan?.response_type ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Classification</dt>
              <dd>
                {draft.reviewed_classification?.email_type ?? "Unavailable"} ·{" "}
                {draft.reviewed_classification?.review_status ?? "Unknown"}
              </dd>
            </div>
          </dl>
          <h3>Source email</h3>
          <strong>{draft.source_email?.subject}</strong>
          <small>
            {draft.source_email?.sender_name} ·{" "}
            {draft.source_email?.sender_email}
          </small>
          <pre className="source-preview">
            {draft.source_email?.body_text ?? "Text evidence unavailable"}
          </pre>
          <h3>Requested items</h3>
          <div className="compact-list">
            {draft.requested_items?.map((item) => (
              <div key={item.id}>
                <Status value={item.status} />
                <span>{item.item_text}</span>
              </div>
            ))}
            {!draft.requested_items?.length && <p>None recorded.</p>}
          </div>
          <h3>Template & signature</h3>
          <p>
            {draft.template?.name ?? "Template unavailable"} · version{" "}
            {draft.template?.version ?? "—"}
          </p>
          <p>Controlled licensing signature is applied deterministically.</p>
          <p>
            AI wording is{" "}
            {capabilities.data?.response_ai_drafting_enabled
              ? "enabled as a review-only suggestion"
              : "disabled"}
            ; it never controls recipients, documents, approval, send, move, or
            completion.
          </p>
        </aside>

        <section className="panel editor-panel">
          <h2>Reviewer revision</h2>
          <label>
            Subject
            <input
              value={subject}
              disabled={!mayEdit}
              onChange={(event) => setSubject(event.target.value)}
            />
          </label>
          <label>
            Response body
            <textarea
              rows={18}
              value={body}
              disabled={!mayEdit}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <label>
            Change reason
            <input
              value={changeReason}
              disabled={!mayEdit}
              onChange={(event) => setChangeReason(event.target.value)}
            />
          </label>
          <button
            onClick={() => save.mutate()}
            disabled={busy || !mayEdit || changeReason.trim().length < 2}
          >
            Save revision and synchronize Graph
          </button>
          {capabilities.data?.response_ai_drafting_enabled && (
            <button
              className="secondary"
              disabled={busy || !mayEdit}
              onClick={() =>
                action.mutate({
                  path: "/ai-suggestion",
                  body: expectation(draft),
                })
              }
            >
              Generate review-only wording suggestion
            </button>
          )}
          <div className="revision-summary">
            <span>Local revision {draft.local_revision}</span>
            <span>
              Graph sync{" "}
              {draft.graph_last_synced_at
                ? new Date(draft.graph_last_synced_at).toLocaleString()
                : "not started"}
            </span>
            <span>
              Immutable Graph ID{" "}
              {draft.graph_draft_message_id ? "retained" : "not created"}
            </span>
          </div>
          <h2>Revision diff</h2>
          {history.isLoading ? (
            <Loading />
          ) : history.error ? (
            <ErrorState error={history.error} />
          ) : (
            <DraftDiff versions={history.data ?? []} />
          )}
        </section>

        <aside className="panel draft-controls">
          <h2>Recipients & readiness</h2>
          <label>
            To recipients
            <input
              value={to}
              disabled={!mayEdit}
              onChange={(event) => setTo(event.target.value)}
            />
          </label>
          <label>
            CC recipients
            <input
              value={cc}
              disabled={!mayEdit}
              onChange={(event) => setCc(event.target.value)}
            />
          </label>
          <p>
            Mode: {draft.response_plan?.recipient_mode ?? "REPLY"}. Reply-all
            and BCC require explicit policy approval.
          </p>
          {draft.external_recipient_domains?.length ? (
            <div className="warning-box">
              External domains: {draft.external_recipient_domains.join(", ")}
            </div>
          ) : null}
          <h3>Readiness checks</h3>
          <div className="compact-list">
            {draft.validation_findings?.length ? (
              draft.validation_findings.map((finding) => (
                <div key={finding}>
                  <span className="check" />
                  <span>{finding.replaceAll("_", " ")}</span>
                </div>
              ))
            ) : (
              <div>
                <span className="check done" />
                <span>No current blockers</span>
              </div>
            )}
          </div>
          <h3>Controlled attachments</h3>
          {draft.attachments.map((item) => (
            <div className="attachment-card" key={item.id}>
              <strong>{item.filename}</strong>
              <small>
                {item.document_approval_status} ·{" "}
                {item.document_lifecycle_status} ·{" "}
                {item.document_storage_status}
              </small>
              <Status value={item.status} />
              {mayEdit && (
                <button
                  className="danger-link"
                  onClick={() => remove.mutate(item.id)}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <details>
            <summary>Add an approved document</summary>
            <div className="document-picker">
              {!capabilities.data?.attachments_enabled && (
                <p>Controlled attachments are disabled by policy.</p>
              )}
              {documents.data?.items
                .filter(
                  (document) =>
                    document.current_version_id &&
                    !selectedDocumentIds.has(document.id),
                )
                .map((document) => (
                  <div key={document.id}>
                    <div>
                      <strong>{document.canonical_title}</strong>
                      <small>
                        {document.current_filename} ·{" "}
                        {document.expiry_date ?? "No expiry"}
                      </small>
                    </div>
                    <button
                      className="secondary"
                      disabled={
                        !mayEdit ||
                        busy ||
                        !capabilities.data?.attachments_enabled
                      }
                      onClick={() => attach.mutate(document)}
                    >
                      Select
                    </button>
                  </div>
                ))}
            </div>
          </details>
          <div className="stacked-actions">
            {!draft.graph_draft_message_id && (
              <button
                disabled={busy}
                onClick={() =>
                  action.mutate({
                    path: "/graph-draft",
                    body: expectation(draft),
                  })
                }
              >
                Create Graph reply draft
              </button>
            )}
            {draft.draft_status === "GRAPH_DRAFT_PENDING" && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => action.mutate({ path: "/reconcile" })}
              >
                Reconcile ambiguous draft creation
              </button>
            )}
            {draft.graph_draft_message_id && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => action.mutate({ path: "/graph-sync" })}
              >
                Check Outlook edits
              </button>
            )}
            <button
              disabled={
                busy ||
                !draft.graph_draft_message_id ||
                Boolean(draft.validation_findings?.length) ||
                !mayEdit
              }
              onClick={() =>
                action.mutate({
                  path: "/submit-approval",
                  body: expectation(draft),
                })
              }
            >
              Submit exact snapshot for send approval
            </button>
          </div>
          {error && <ErrorState error={error} />}
        </aside>
      </div>
    </main>
  );
}
