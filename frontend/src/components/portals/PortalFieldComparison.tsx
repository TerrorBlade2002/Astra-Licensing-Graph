import type { PortalRunField } from "../../types";
import { Status } from "../common/States";

export function PortalFieldComparison({
  fields,
}: {
  fields: PortalRunField[];
}) {
  return (
    <section className="panel wide">
      <h2>Reviewed field comparison</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Internal field</th>
              <th>Approved source</th>
              <th>Portal value</th>
              <th>Status</th>
              <th>Discrepancy</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.id}>
                <td>{field.label ?? field.portal_field_key}</td>
                <td>{field.approved_source_type ?? "Manual review"}</td>
                <td>{field.displayed_value_redacted ?? "Not entered"}</td>
                <td>
                  <Status value={field.status} />
                </td>
                <td>{field.discrepancy_code ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <small className="muted">
        Restricted values remain masked. Human-only fields are never
        auto-populated.
      </small>
    </section>
  );
}
