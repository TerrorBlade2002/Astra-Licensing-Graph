import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { CalendarEntry } from "../types";

export function ComplianceCalendarPage() {
  const query = useQuery({
    queryKey: ["compliance-calendar"],
    queryFn: () => api<CalendarEntry[]>("/calendar"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Statutory and internal dates</span>
          <h1>Compliance calendar</h1>
          <p>
            Business-day movement is applied only when the governing rule
            explicitly allows it.
          </p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Due</th>
              <th>Obligation</th>
              <th>Deadline</th>
              <th>Urgency</th>
              <th>Owner</th>
              <th>Kind</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((row) => (
              <tr key={row.deadline_id}>
                <td>
                  <strong>{new Date(row.due_at).toLocaleDateString()}</strong>
                  <small>
                    {row.internal_target_at
                      ? `Internal ${new Date(row.internal_target_at).toLocaleDateString()}`
                      : ""}
                  </small>
                </td>
                <td>{row.title}</td>
                <td>{row.deadline_type}</td>
                <td>
                  <Status value={row.status} />
                </td>
                <td>{row.assigned_owner ?? "Unassigned"}</td>
                <td>{row.is_statutory ? "Statutory" : "Internal"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
