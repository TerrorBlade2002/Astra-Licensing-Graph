import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading } from "../components/common/States";

type Summary = {
  pending_reviews: number;
  claimed_reviews: number;
  tasks_due_today: number;
  tasks_overdue: number;
  tasks_due_7_days: number;
  tasks_due_30_days: number;
  failed_classification_jobs: number;
};
export function DashboardPage() {
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Summary>("/dashboard/summary"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  const s = query.data!;
  return (
    <main>
      <section className="hero">
        <div>
          <span className="eyebrow">Wednesday · operational brief</span>
          <h1>
            Good morning. <em>{s.pending_reviews} decisions</em> need human
            attention.
          </h1>
          <p>
            Classifications remain paused until a reviewer confirms the
            evidence. No outbound action is enabled.
          </p>
          <div className="hero-actions">
            <Link className="primary button" to="/reviews">
              Open review queue
            </Link>
            <Link className="secondary button" to="/tasks">
              View task board
            </Link>
          </div>
        </div>
        <div className="hero-orbit">
          <div className="orbit-value">{s.pending_reviews}</div>
          <span>pending review</span>
          <small>{s.claimed_reviews} currently claimed</small>
        </div>
      </section>
      <section className="metric-grid" aria-label="Operational metrics">
        <article>
          <small>Due today</small>
          <strong>{s.tasks_due_today}</strong>
          <span>licensing tasks</span>
        </article>
        <article className={s.tasks_overdue ? "attention" : ""}>
          <small>Overdue</small>
          <strong>{s.tasks_overdue}</strong>
          <span>needs escalation</span>
        </article>
        <article>
          <small>Next 7 days</small>
          <strong>{s.tasks_due_7_days}</strong>
          <span>scheduled work</span>
        </article>
        <article>
          <small>Classification failures</small>
          <strong>{s.failed_classification_jobs}</strong>
          <span>review required</span>
        </article>
      </section>
      <section className="split">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Workflow posture</span>
              <h2>Controlled by design</h2>
            </div>
          </div>
          <div className="control-list">
            <div>
              <span>01</span>
              <div>
                <strong>Evidence captured</strong>
                <p>Email and attachments remain the source of truth.</p>
              </div>
              <b>Complete</b>
            </div>
            <div>
              <span>02</span>
              <div>
                <strong>Classification proposed</strong>
                <p>Deterministic rules run before optional model enrichment.</p>
              </div>
              <b>Active</b>
            </div>
            <div>
              <span>03</span>
              <div>
                <strong>Human decision</strong>
                <p>
                  Approve, correct, reject, or reclassify with a durable diff.
                </p>
              </div>
              <b>Required</b>
            </div>
            <div>
              <span>04</span>
              <div>
                <strong>Task created</strong>
                <p>Only approved work crosses this boundary.</p>
              </div>
              <b>Gated</b>
            </div>
          </div>
        </article>
        <article className="panel dark-panel">
          <span className="eyebrow">Milestone boundary</span>
          <h2>Ready to send does not mean sent.</h2>
          <p>
            The portal creates operational tasks. It does not draft mail, send
            correspondence, move messages, or submit to regulators.
          </p>
          <div className="boundary-tags">
            <span>No drafts</span>
            <span>No sends</span>
            <span>No mailbox moves</span>
          </div>
        </article>
      </section>
    </main>
  );
}
