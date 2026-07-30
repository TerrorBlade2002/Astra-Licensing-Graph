import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
type Finding = {
  code: string;
  severity: string;
  entity_type: string;
  entity_id: string | null;
  detail: string;
};
type Report = {
  generated_at: string;
  total_findings: number;
  findings_by_code: Record<string, number>;
  findings: Finding[];
};
export function DataQualityPage() {
  const query = useQuery({
    queryKey: ["licensing-data-quality"],
    queryFn: () => api<Report>("/licensing-dashboard/data-quality"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Reconciliation controls</span>
          <h1>Licensing data quality</h1>
          <p>Generated {new Date(query.data!.generated_at).toLocaleString()}</p>
        </div>
        <strong className="finding-count">{query.data?.total_findings}</strong>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Finding</th>
              <th>Record</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.findings.map((row, index) => (
              <tr key={`${row.code}-${row.entity_id}-${index}`}>
                <td>
                  <Status value={row.severity} />
                </td>
                <td>{row.code}</td>
                <td>
                  <small>{row.entity_type}</small>
                  {row.entity_id ?? "—"}
                </td>
                <td>{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
