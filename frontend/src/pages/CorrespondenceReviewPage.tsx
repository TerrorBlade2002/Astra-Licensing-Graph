import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ErrorState, Loading } from "../components/common/States";

type MatchSignal = { code: string; detail: string; weight: number };

export type CaseEmailLink = {
  id: string;
  compliance_case_id: string;
  case_key: string | null;
  email_id: string;
  conversation_id: string | null;
  link_status: string;
  match_score: number | null;
  match_reasons: { signals?: MatchSignal[] };
  proposed_at: string;
  email_subject: string | null;
  email_sender: string | null;
  email_received_at: string | null;
  legal_entity_name: string | null;
};

export function CorrespondenceReviewPage() {
  const queryClient = useQueryClient();
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const pending = useQuery({
    queryKey: ["case-email-links"],
    queryFn: () => api<CaseEmailLink[]>("/case-email-links"),
  });

  const decide = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string;
      action: "confirm" | "reject";
    }) =>
      api<CaseEmailLink>(`/case-email-links/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ reason: reasons[id] || null }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["case-email-links"] });
      queryClient.invalidateQueries({ queryKey: ["renewal-timeline"] });
    },
  });

  if (pending.isLoading) return <Loading />;
  if (pending.error) return <ErrorState error={pending.error} />;
  const links = pending.data ?? [];

  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Correspondence review</span>
          <h1>Proposed case links</h1>
          <p>
            The system suggests which case an email belongs to. Nothing is
            attached to a case file until you confirm it here.
          </p>
        </div>
      </div>

      {links.length === 0 ? (
        <section className="panel">
          <p className="muted">No proposals are waiting for review.</p>
        </section>
      ) : (
        <div className="stack">
          {links.map((link) => (
            <section className="panel" key={link.id}>
              <div className="link-head">
                <div>
                  <strong>{link.email_subject ?? "(no subject)"}</strong>
                  <small>
                    From {link.email_sender ?? "unknown sender"}
                    {link.email_received_at
                      ? ` · ${new Date(link.email_received_at).toLocaleString()}`
                      : ""}
                  </small>
                </div>
                <span className="match-score">
                  {link.match_score !== null
                    ? `${Math.round(link.match_score * 100)}% match`
                    : "unscored"}
                </span>
              </div>

              <dl className="detail-list">
                <dt>Proposed case</dt>
                <dd>{link.case_key ?? link.compliance_case_id}</dd>
                <dt>Legal entity</dt>
                <dd>{link.legal_entity_name ?? "Unknown"}</dd>
              </dl>

              <h3>Why this was proposed</h3>
              <ul className="signal-list">
                {(link.match_reasons.signals ?? []).map((signal) => (
                  <li key={signal.code}>
                    <code>{signal.code}</code> {signal.detail}
                  </li>
                ))}
              </ul>

              <label htmlFor={`reason-${link.id}`}>
                Decision note (optional)
              </label>
              <input
                id={`reason-${link.id}`}
                value={reasons[link.id] ?? ""}
                onChange={(event) =>
                  setReasons((current) => ({
                    ...current,
                    [link.id]: event.target.value,
                  }))
                }
                placeholder="Why this thread does or does not belong to the case"
              />

              <div className="button-row">
                <button
                  type="button"
                  disabled={decide.isPending}
                  onClick={() =>
                    decide.mutate({ id: link.id, action: "confirm" })
                  }
                >
                  Confirm link
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={decide.isPending}
                  onClick={() =>
                    decide.mutate({ id: link.id, action: "reject" })
                  }
                >
                  Reject
                </button>
              </div>
            </section>
          ))}
        </div>
      )}
      {decide.error ? <ErrorState error={decide.error} /> : null}
    </main>
  );
}
