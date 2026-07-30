import type { PortalRunDocument } from "../../types";
import { Status } from "../common/States";

export function DocumentUploadStatus({
  documents,
}: {
  documents: PortalRunDocument[];
}) {
  return (
    <section className="panel wide">
      <h2>Approved document uploads</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Expected document</th>
              <th>Version</th>
              <th>Hash</th>
              <th>Portal category</th>
              <th>Portal display</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.expected_filename}</td>
                <td>{document.document_version_id.slice(0, 8)}</td>
                <td>{document.expected_sha256.slice(0, 12)}…</td>
                <td>{document.portal_document_category ?? "Default"}</td>
                <td>{document.portal_display_name ?? "Not uploaded"}</td>
                <td>
                  <Status value={document.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
