import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { RequirementAssessment, RequirementResult } from "../types";

type Detail = {
  assessment: RequirementAssessment;
  results: RequirementResult[];
  advisory_notice: string;
};
export function RequirementResultPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["assessment-detail", id],
    queryFn: () => api<Detail>(`/requirement-assessments/${id}`),
    enabled: !!id,
  });
  const review = useMutation({
    mutationFn: (result: RequirementResult) =>
      api(`/requirement-results/${result.id}/review`, {
        method: "POST",
        body: JSON.stringify({
          reviewed_outcome: result.outcome,
          notes: "Reviewed in portal.",
        }),
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["assessment-detail", id] }),
  });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Requirement result</span>
          <h1>{query.data?.assessment.assessment_key}</h1>
          <p>{query.data?.advisory_notice}</p>
        </div>
        <Status value={query.data?.assessment.status ?? ""} />
      </div>
      <div className="result-grid">
        {query.data?.results.map((result) => (
          <article className="panel" key={result.id}>
            <div className="panel-title">
              <h2>{result.outcome.replaceAll("_", " ")}</h2>
              <Status value={result.source_freshness_status} />
            </div>
            <p>{result.explanation}</p>
            <h3>Filing channels</h3>
            <div className="chip-list">
              {result.filing_channels.map((channel) => (
                <Status value={channel} key={channel} />
              ))}
            </div>
            <h3>Missing facts</h3>
            <ul>
              {result.missing_facts.map((fact, index) => (
                <li key={index}>{String(fact)}</li>
              ))}
            </ul>
            <h3>Sources</h3>
            {result.source_citations.map((citation, index) => (
              <pre className="citation" key={index}>
                {JSON.stringify(citation, null, 2)}
              </pre>
            ))}
            <button
              disabled={!!result.reviewed_outcome || review.isPending}
              onClick={() => review.mutate(result)}
            >
              {result.reviewed_outcome ? "Reviewed" : "Confirm human review"}
            </button>
          </article>
        ))}
      </div>
    </main>
  );
}
