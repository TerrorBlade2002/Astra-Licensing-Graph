import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
type Source = {
  id: string;
  source_key: string;
  title: string;
  source_type: string;
  authority_level: string;
  verification_status: string;
  last_verified_at: string | null;
  official_url: string | null;
};
export function RequirementSourcesPage() {
  const query = useQuery({
    queryKey: ["requirement-sources"],
    queryFn: () => api<Source[]>("/requirement-sources"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Versioned provenance</span>
          <h1>Requirement sources</h1>
          <p>
            Changed content creates a review snapshot; active rules never change
            silently.
          </p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Type</th>
              <th>Authority</th>
              <th>Verification</th>
              <th>Last checked</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((row) => (
              <tr key={row.id}>
                <td>
                  <strong>{row.title}</strong>
                  <small>{row.source_key}</small>
                </td>
                <td>{row.source_type}</td>
                <td>{row.authority_level}</td>
                <td>
                  <Status value={row.verification_status} />
                </td>
                <td>
                  {row.last_verified_at
                    ? new Date(row.last_verified_at).toLocaleDateString()
                    : "Never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
