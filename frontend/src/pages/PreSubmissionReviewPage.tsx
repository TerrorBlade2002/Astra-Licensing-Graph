import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading } from "../components/common/States";
import { PreSubmissionSnapshot } from "../components/portals/PreSubmissionSnapshot";
import { ValidationMessagePanel } from "../components/portals/ValidationMessagePanel";
import type { PreSubmissionSnapshot as Snapshot } from "../types";

export function PreSubmissionReviewPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const snapshot = useQuery({
    queryKey: ["pre-submission-snapshot", id],
    queryFn: () => api<Snapshot>(`/pre-submission-snapshots/${id}`),
    enabled: !!id,
  });
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api(`/pre-submission-snapshots/${id}/${decision}`, {
        method: "POST",
        body: JSON.stringify({
          reason:
            decision === "reject" ? "Reviewer found a discrepancy." : undefined,
        }),
      }),
    onSuccess: () =>
      void client.invalidateQueries({
        queryKey: ["pre-submission-snapshot", id],
      }),
  });
  if (snapshot.isLoading) return <Loading />;
  if (snapshot.error) return <ErrorState error={snapshot.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Exact reviewed state</span>
          <h1>Pre-submission review</h1>
          <p>
            <Link to={`/portal-runs/${snapshot.data!.portal_run_id}`}>
              Return to portal run
            </Link>
          </p>
        </div>
      </div>
      <div className="split">
        <PreSubmissionSnapshot
          snapshot={snapshot.data!}
          pending={decide.isPending}
          onApprove={() => decide.mutate("approve")}
          onReject={() => decide.mutate("reject")}
        />
        <ValidationMessagePanel
          messages={snapshot.data!.portal_validation_messages}
        />
      </div>
      <section className="panel wide">
        <h2>Blocking discrepancies</h2>
        {snapshot.data!.discrepancy_report.length === 0 ? (
          <p>No blockers in this exact snapshot.</p>
        ) : (
          <pre>
            {JSON.stringify(snapshot.data!.discrepancy_report, null, 2)}
          </pre>
        )}
      </section>
      {decide.error && <ErrorState error={decide.error} />}
    </main>
  );
}
