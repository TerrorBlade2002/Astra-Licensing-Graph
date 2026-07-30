import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
type Doc = {
  id: string;
  display_name: string;
  document_type: string;
  approval_status: string;
  lifecycle_status: string;
  jurisdiction: string | null;
  current_filename: string | null;
};
type StorageStatus = {
  backend: string;
  bucket?: string | null;
  site_id?: string | null;
  root?: string | null;
  credentials_configured?: boolean;
};

const BACKEND_LABELS: Record<string, string> = {
  sharepoint: "SharePoint (repository of record)",
  r2: "Cloudflare R2 object storage",
  filesystem: "Local filesystem (development only)",
};

export function DocumentsPage() {
  const q = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<{ items: Doc[] }>("/documents?page_size=50"),
  });
  const storage = useQuery({
    queryKey: ["storage-status"],
    queryFn: () => api<StorageStatus>("/integrations/storage/status"),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Governed repository</span>
          <h1>Licensing documents</h1>
          <p>
            Controlled metadata and downloads—never unrestricted SharePoint
            links.
          </p>
        </div>
        {storage.data ? (
          <div className="storage-badge">
            <span className="eyebrow">Content stored in</span>
            <strong>
              {BACKEND_LABELS[storage.data.backend] ?? storage.data.backend}
            </strong>
            {storage.data.bucket ? <small>{storage.data.bucket}</small> : null}
          </div>
        ) : null}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Document</th>
              <th>Type</th>
              <th>Jurisdiction</th>
              <th>Approval</th>
              <th>Lifecycle</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.items.map((d) => (
              <tr key={d.id}>
                <td>
                  <strong>{d.display_name}</strong>
                  <small>{d.current_filename}</small>
                </td>
                <td>{d.document_type}</td>
                <td>{d.jurisdiction ?? "—"}</td>
                <td>
                  <Status value={d.approval_status} />
                </td>
                <td>
                  <Status value={d.lifecycle_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {q.data?.items.length === 0 && (
        <div className="empty-state">
          <h2>No governed documents yet</h2>
          <p>Promoted evidence will appear here after repository approval.</p>
        </div>
      )}
    </main>
  );
}
