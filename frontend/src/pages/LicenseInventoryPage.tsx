import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { LicenseRecord } from "../types";

export function LicenseInventoryPage() {
  const query = useQuery({
    queryKey: ["license-inventory"],
    queryFn: () => api<{ items: LicenseRecord[] }>("/licenses?limit=250"),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Central master tracker</span>
          <h1>License inventory</h1>
          <p>
            NMLS is shown as a filing channel, independently of applicability.
          </p>
        </div>
        <Link className="primary" to="/licensing/import">
          Import tracker
        </Link>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>License</th>
              <th>Status</th>
              <th>Channel</th>
              <th>Expiration</th>
              <th>Next renewal</th>
              <th>Owner</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/licensing/licenses/${row.id}`}>
                    <strong>{row.license_number ?? row.license_key}</strong>
                  </Link>
                  <small>{row.license_key}</small>
                </td>
                <td>
                  <Status value={row.current_status} />
                </td>
                <td>
                  <Status value={row.filing_channel} />
                </td>
                <td>{row.expiration_date ?? "—"}</td>
                <td>{row.renewal_due_date ?? "—"}</td>
                <td>{row.responsible_owner ?? "Unassigned"}</td>
                <td>{row.source_confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
