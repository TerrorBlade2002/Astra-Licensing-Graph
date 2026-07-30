import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { InformationValue } from "../types";

type Definition = {
  id: string;
  information_key: string;
  name: string;
  sensitivity: string;
  category: string;
};
export function InformationRegistryPage() {
  const values = useQuery({
    queryKey: ["information-values"],
    queryFn: () => api<InformationValue[]>("/information-values"),
  });
  const definitions = useQuery({
    queryKey: ["information-definitions"],
    queryFn: () => api<Definition[]>("/information-definitions"),
  });
  if (values.isLoading || definitions.isLoading) return <Loading />;
  if (values.error || definitions.error)
    return <ErrorState error={values.error ?? definitions.error} />;
  const names = new Map(definitions.data?.map((item) => [item.id, item]));
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Approved reusable answers</span>
          <h1>Information registry</h1>
          <p>
            Restricted values stay masked; stale or unapproved values cannot
            autofill forms.
          </p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Information</th>
              <th>Masked value</th>
              <th>Status</th>
              <th>Sensitivity</th>
              <th>Owner</th>
              <th>Valid to</th>
              <th>Last used</th>
            </tr>
          </thead>
          <tbody>
            {values.data?.map((row) => {
              const definition = names.get(row.information_definition_id);
              return (
                <tr key={row.id}>
                  <td>
                    <strong>
                      {definition?.name ?? row.information_definition_id}
                    </strong>
                    <small>{definition?.information_key}</small>
                  </td>
                  <td className="masked-value">
                    {row.display_value_redacted ?? "••••"}
                  </td>
                  <td>
                    <Status value={row.status} />
                  </td>
                  <td>
                    <Status value={definition?.sensitivity ?? "UNKNOWN"} />
                  </td>
                  <td>{row.owner_actor ?? "Unassigned"}</td>
                  <td>{row.valid_to ?? "—"}</td>
                  <td>
                    {row.last_used_at
                      ? new Date(row.last_used_at).toLocaleDateString()
                      : "Never"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
