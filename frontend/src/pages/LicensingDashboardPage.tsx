import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { ComplianceCase, DashboardSummary } from "../types";

export function LicensingDashboardPage() {
  const summary = useQuery({
    queryKey: ["licensing-summary"],
    queryFn: () => api<DashboardSummary>("/licensing-dashboard/summary"),
  });
  const blocked = useQuery({
    queryKey: ["blocked-cases"],
    queryFn: () =>
      api<Array<ComplianceCase & { stage: string }>>(
        "/licensing-dashboard/blocked-cases",
      ),
  });
  if (summary.isLoading) return <Loading />;
  if (summary.error) return <ErrorState error={summary.error} />;
  const data = summary.data!;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Milestone 6 control plane</span>
          <h1>Licensing operations</h1>
          <p>{data.advisory_notice}</p>
        </div>
      </div>
      <section className="metrics">
        <div>
          <strong>{data.licenses_active}</strong>
          <span>Active licenses</span>
        </div>
        <div>
          <strong>{data.licenses_expiring["30"] ?? 0}</strong>
          <span>Due in 30 days</span>
        </div>
        <div>
          <strong>{data.obligations_overdue}</strong>
          <span>Overdue obligations</span>
        </div>
        <div>
          <strong>{data.cases_open}</strong>
          <span>Open cases</span>
        </div>
        <div>
          <strong>{data.packets_missing_items}</strong>
          <span>Packets missing items</span>
        </div>
        <div>
          <strong>{data.forms_waiting_signature}</strong>
          <span>Waiting signature</span>
        </div>
      </section>
      <div className="split">
        <section className="panel">
          <div className="panel-title">
            <h2>Cases by stage</h2>
          </div>
          <div className="licensing-stage-grid">
            {Object.entries(data.cases_by_stage).map(([stage, count]) => (
              <div key={stage}>
                <Status value={stage} />
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>Blocked cases</h2>
            <Link to="/licensing/cases">All cases</Link>
          </div>
          {blocked.data?.map((item) => (
            <Link
              className="work-item"
              to={`/licensing/cases/${item.id}`}
              key={item.id}
            >
              <strong>{item.case_key}</strong>
              <span>{item.stage ?? item.current_stage}</span>
              <small>{item.blocked_reason ?? "Review blocker"}</small>
            </Link>
          ))}
          {!blocked.data?.length && <p className="muted">No blocked cases.</p>}
        </section>
      </div>
    </main>
  );
}
