import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, apiForm } from "../api/client";
import { ErrorState, Status } from "../components/common/States";
type Plan = {
  import_run_id: string;
  status: string;
  mapping_required: boolean;
  headers?: string[];
  counts?: Record<string, number>;
  sample_rows?: Array<Record<string, string>>;
  notes?: string[];
};
export function MasterTrackerImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [mapping, setMapping] = useState("{}");
  const [applied, setApplied] = useState<Record<string, unknown> | null>(null);
  const upload = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.append("file", file!);
      if (mapping.trim() !== "{}") body.append("mapping_json", mapping);
      return apiForm<Plan>("/tracker-imports", body);
    },
    onSuccess: setPlan,
  });
  const apply = useMutation({
    mutationFn: () =>
      api<Record<string, unknown>>(
        `/tracker-imports/${plan?.import_run_id}/apply`,
        { method: "POST", body: JSON.stringify({ confirm: true }) },
      ),
    onSuccess: setApplied,
  });
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Dry run before mutation</span>
          <h1>Master tracker import</h1>
          <p>
            CSV/XLSX formulas are treated as data; macros are rejected and
            conflicts require review.
          </p>
        </div>
      </div>
      <section className="panel import-flow">
        <label>
          Tracker file
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Column mapping JSON
          <textarea
            rows={8}
            value={mapping}
            onChange={(event) => setMapping(event.target.value)}
          />
        </label>
        <button
          disabled={!file || upload.isPending}
          onClick={() => upload.mutate()}
        >
          {upload.isPending ? "Planning…" : "Run dry-run plan"}
        </button>
        {upload.error && <ErrorState error={upload.error} />}
      </section>
      {plan && (
        <section className="panel">
          <div className="panel-title">
            <h2>Dry-run result</h2>
            <Status value={plan.status} />
          </div>
          {plan.mapping_required ? (
            <>
              <p>Map the detected headers and run the plan again.</p>
              <div className="chip-list">
                {plan.headers?.map((header) => (
                  <span className="tag" key={header}>
                    {header}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <>
              <pre>{JSON.stringify(plan.counts, null, 2)}</pre>
              <button
                disabled={apply.isPending || (plan.counts?.conflict ?? 0) > 0}
                onClick={() => apply.mutate()}
              >
                Confirm and apply reviewed plan
              </button>
            </>
          )}
        </section>
      )}
      {applied && (
        <section className="send-confirmation">
          <strong>Import applied</strong>
          <pre>{JSON.stringify(applied, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}
