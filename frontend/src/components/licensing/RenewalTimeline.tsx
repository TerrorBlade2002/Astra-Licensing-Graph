import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ErrorState, Loading, Status } from "../common/States";

export type TimelineEntry = {
  occurred_at: string;
  category: string;
  summary: string;
  detail: string | null;
  actor_id: string | null;
  case_id: string | null;
  case_key: string | null;
  email_id: string | null;
  reference: Record<string, unknown>;
};

export type RenewalTimeline = {
  license_id: string;
  license_key: string;
  current_status: string;
  expiration_date: string | null;
  renewal_due_date: string | null;
  open_case_count: number;
  active_stage: string | null;
  entries: TimelineEntry[];
};

const CATEGORY_LABELS: Record<string, string> = {
  LICENSE_STATUS: "Licence",
  CASE_STAGE: "Case stage",
  EMAIL_RECEIVED: "Email received",
  EMAIL_SENT: "Reply sent",
};

export function RenewalTimeline({ licenseId }: { licenseId: string }) {
  const timeline = useQuery({
    queryKey: ["renewal-timeline", licenseId],
    queryFn: () =>
      api<RenewalTimeline>(`/licenses/${licenseId}/renewal-timeline`),
    enabled: !!licenseId,
  });

  if (timeline.isLoading) return <Loading />;
  if (timeline.error) return <ErrorState error={timeline.error} />;
  const data = timeline.data!;

  return (
    <section className="panel">
      <h2>Renewal progress</h2>
      <div className="stage-summary">
        <div>
          <span className="eyebrow">Current stage</span>
          <strong>{data.active_stage ?? "No open case"}</strong>
        </div>
        <div>
          <span className="eyebrow">Open cases</span>
          <strong>{data.open_case_count}</strong>
        </div>
        <div>
          <span className="eyebrow">Renewal due</span>
          <strong>
            {data.renewal_due_date ?? data.expiration_date ?? "Not recorded"}
          </strong>
        </div>
      </div>

      {data.entries.length === 0 ? (
        <p className="muted">
          No recorded activity yet. Correspondence appears here once a reviewer
          confirms that an email thread belongs to this licence&rsquo;s case.
        </p>
      ) : (
        <ol className="renewal-timeline">
          {data.entries.map((entry, index) => (
            <li
              key={`${entry.occurred_at}-${index}`}
              data-category={entry.category}
            >
              <div className="renewal-timeline-head">
                <Status
                  value={CATEGORY_LABELS[entry.category] ?? entry.category}
                />
                <time dateTime={entry.occurred_at}>
                  {new Date(entry.occurred_at).toLocaleString()}
                </time>
              </div>
              <strong>{entry.summary}</strong>
              {entry.detail ? <p>{entry.detail}</p> : null}
              <small>
                {entry.case_key ? `Case ${entry.case_key}` : null}
                {entry.case_key && entry.actor_id ? " · " : null}
                {entry.actor_id ? `By ${entry.actor_id}` : null}
              </small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
