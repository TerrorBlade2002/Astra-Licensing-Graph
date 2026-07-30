import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { api, apiDownload } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
type Instance = {
  id: string;
  instance_key: string;
  status: string;
  signature_required: boolean;
  signature_status: string;
};
type Detail = Instance & {
  fields: Array<{
    field_key: string;
    label: string;
    status: string;
    display_value: string | null;
    source_type: string;
    sensitivity: string;
    is_masked: boolean;
  }>;
  missing_fields: unknown[];
  approved_draft_sha256: string | null;
  generated_document_id: string | null;
  worksheet_document_id: string | null;
};
export function FormPreparationPage() {
  const [params, setParams] = useSearchParams();
  const [generationQueued, setGenerationQueued] = useState(false);
  const id = params.get("instance");
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["form-instances"],
    queryFn: () => api<Instance[]>("/form-instances"),
  });
  const detail = useQuery({
    queryKey: ["form-instance", id],
    queryFn: () => api<Detail>(`/form-instances/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      generationQueued && !query.state.data?.generated_document_id
        ? 2000
        : false,
  });
  const generate = useMutation({
    mutationFn: () =>
      api(`/form-instances/${id}/generate`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          flatten: false,
        }),
      }),
    onSuccess: () => {
      setGenerationQueued(true);
      void client.invalidateQueries({ queryKey: ["form-instance", id] });
    },
  });
  useEffect(() => {
    if (detail.data?.generated_document_id) setGenerationQueued(false);
  }, [detail.data?.generated_document_id]);
  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorState error={list.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Draft preparation only</span>
          <h1>Form preparation</h1>
          <p>
            No signature is inserted and no filing portal is contacted or
            submitted.
          </p>
        </div>
      </div>
      <div className="split">
        <section className="panel">
          <h2>Form instances</h2>
          {list.data?.map((row) => (
            <button
              className="work-item"
              key={row.id}
              onClick={() => setParams({ instance: row.id })}
            >
              <strong>{row.instance_key}</strong>
              <Status value={row.status} />
              <small>
                {row.signature_required
                  ? row.signature_status
                  : "No signature required"}
              </small>
            </button>
          ))}
        </section>
        <section className="panel">
          {!id ? (
            <p>Select a form instance.</p>
          ) : detail.isLoading ? (
            <Loading />
          ) : detail.error ? (
            <ErrorState error={detail.error} />
          ) : (
            <>
              <div className="panel-title">
                <h2>{detail.data?.instance_key}</h2>
                <Status value={detail.data?.status ?? ""} />
              </div>
              {detail.data?.fields.map((field) => (
                <div className="form-field-row" key={field.field_key}>
                  <div>
                    <strong>{field.label}</strong>
                    <small>
                      {field.field_key} · {field.source_type} ·{" "}
                      {field.sensitivity}
                    </small>
                  </div>
                  <span className={field.is_masked ? "masked-value" : ""}>
                    {field.display_value ?? "—"}
                  </span>
                  <Status value={field.status} />
                </div>
              ))}
              {detail.data?.signature_required && (
                <div className="send-confirmation">
                  <strong>Human signature required</strong>
                  <p>
                    The approved draft hash must match the version sent for
                    signature. A separately uploaded signed document is
                    required.
                  </p>
                </div>
              )}
              <div className="stacked-actions">
                {!detail.data?.generated_document_id && (
                  <button
                    disabled={
                      generate.isPending ||
                      detail.data?.missing_fields.length !== 0
                    }
                    onClick={() => generate.mutate()}
                  >
                    {generationQueued
                      ? "Generating governed draft…"
                      : "Generate governed draft"}
                  </button>
                )}
                {detail.data?.generated_document_id && (
                  <button
                    onClick={() =>
                      void apiDownload(
                        `/documents/${detail.data?.generated_document_id}/download`,
                        `${detail.data?.instance_key ?? "prepared-form"}.pdf`,
                      )
                    }
                  >
                    Download generated draft
                  </button>
                )}
                <button
                  onClick={() =>
                    void apiDownload(
                      `/form-instances/${id}/worksheet?format=csv`,
                      `${detail.data?.instance_key ?? "form"}-worksheet.csv`,
                    )
                  }
                >
                  Download field worksheet
                </button>
              </div>
              {generate.error && <ErrorState error={generate.error} />}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
