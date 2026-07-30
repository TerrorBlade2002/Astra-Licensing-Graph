import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { ComplianceCase } from "../types";

export function ComplianceCasesPage() {
  const query = useQuery({
    queryKey: ["compliance-cases"],
    queryFn: () => api<ComplianceCase[]>("/compliance-cases"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Operational workspaces</span>
          <h1>Compliance cases</h1>
          <p>
            Renewals, bonds, annual reports, deficiencies, and other
            obligations.
          </p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Type</th>
              <th>Stage</th>
              <th>Status</th>
              <th>Due</th>
              <th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/licensing/cases/${row.id}`}>{row.case_key}</Link>
                </td>
                <td>{row.case_type}</td>
                <td>
                  <Status value={row.current_stage} />
                </td>
                <td>
                  <Status value={row.status} />
                </td>
                <td>{row.statutory_due_date ?? "—"}</td>
                <td>{row.assigned_owner ?? "Unassigned"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
