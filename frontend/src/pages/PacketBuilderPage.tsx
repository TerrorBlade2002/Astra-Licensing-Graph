import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, apiDownload } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";

type Packet = {
  id: string;
  packet_key: string;
  compliance_case_id: string;
  version: number;
  status: string;
  manifest_sha256: string | null;
};
type Detail = Packet & {
  archive_ready: boolean;
  archive_format: string;
  archive_sha256: string | null;
  archive_size_bytes: number | null;
  missing_items: unknown[];
  validation_results: unknown[];
  items: Array<{
    packet_item_key: string;
    document_type: string | null;
    status: string;
    required: boolean;
    filename_in_archive: string | null;
    document_sha256: string | null;
  }>;
};
export function PacketBuilderPage() {
  const [params, setParams] = useSearchParams();
  const packetId = params.get("packet");
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["document-packets"],
    queryFn: () => api<Packet[]>("/document-packets"),
  });
  const detail = useQuery({
    queryKey: ["document-packet", packetId],
    queryFn: () => api<Detail>(`/document-packets/${packetId}`),
    enabled: !!packetId,
    refetchInterval: (query) =>
      query.state.data?.status === "READY_FOR_REVIEW" &&
      !query.state.data.archive_ready
        ? 2000
        : false,
  });
  const action = useMutation({
    mutationFn: (kind: "build" | "approve") =>
      api<Detail>(`/document-packets/${packetId}/${kind}`, {
        method: "POST",
        body: kind === "build" ? JSON.stringify({}) : undefined,
      }),
    onSuccess: () =>
      void client.invalidateQueries({
        queryKey: ["document-packet", packetId],
      }),
  });
  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorState error={list.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Immutable document snapshots</span>
          <h1>Packet builder</h1>
          <p>
            Only approved, current, hash-valid documents from the correct legal
            entity can be included.
          </p>
        </div>
      </div>
      <div className="split">
        <section className="panel">
          <h2>Packets</h2>
          {list.data?.map((row) => (
            <button
              className="work-item"
              key={row.id}
              onClick={() => setParams({ packet: row.id })}
            >
              <strong>{row.packet_key}</strong>
              <Status value={row.status} />
              <small>Version {row.version}</small>
            </button>
          ))}
        </section>
        <section className="panel">
          {!packetId ? (
            <p>Select a packet.</p>
          ) : detail.isLoading ? (
            <Loading />
          ) : detail.error ? (
            <ErrorState error={detail.error} />
          ) : (
            <>
              <div className="panel-title">
                <h2>{detail.data?.packet_key}</h2>
                <Status value={detail.data?.status ?? ""} />
              </div>
              <code className="snapshot-hash">
                {detail.data?.manifest_sha256 ?? "Manifest not built"}
              </code>
              <p className="hint">
                {detail.data?.archive_ready
                  ? detail.data.archive_format === "ZIP"
                    ? `Governed ZIP ready · ${detail.data.archive_size_bytes ?? 0} bytes`
                    : "Manifest-only packet; no ZIP is required by policy."
                  : detail.data?.status === "READY_FOR_REVIEW"
                    ? "The packet worker is retrieving and hash-checking pinned document versions."
                    : "Build the manifest to queue governed archive generation."}
              </p>
              {detail.data?.items.map((item) => (
                <div className="packet-line" key={item.packet_item_key}>
                  <div>
                    <strong>{item.packet_item_key}</strong>
                    <small>{item.document_type}</small>
                  </div>
                  <Status value={item.status} />
                  <small>
                    {item.filename_in_archive ??
                      (item.required ? "Required item missing" : "Optional")}
                  </small>
                </div>
              ))}
              <div className="stacked-actions">
                <button
                  onClick={() => action.mutate("build")}
                  disabled={
                    action.isPending || detail.data?.status === "APPROVED"
                  }
                >
                  Build current version
                </button>
                <button
                  onClick={() => action.mutate("approve")}
                  disabled={
                    action.isPending ||
                    detail.data?.status !== "READY_FOR_REVIEW" ||
                    !detail.data?.archive_ready
                  }
                >
                  Approve immutable packet
                </button>
                {detail.data?.status === "APPROVED" &&
                  detail.data.archive_ready &&
                  detail.data.archive_format === "ZIP" && (
                    <button
                      onClick={() =>
                        void apiDownload(
                          `/document-packets/${packetId}/download`,
                          `${detail.data?.packet_key ?? "packet"}.zip`,
                        )
                      }
                    >
                      Download approved ZIP
                    </button>
                  )}
              </div>
              {action.error && <ErrorState error={action.error} />}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
