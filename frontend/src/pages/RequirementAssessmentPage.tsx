import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { LegalEntity, RequirementAssessment } from "../types";

type Jurisdiction = { id: string; name: string };
type Profile = { id: string; name: string; version: number; status: string };
export function RequirementAssessmentPage() {
  const [entityId, setEntityId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [jurisdictionIds, setJurisdictionIds] = useState<string[]>([]);
  const entities = useQuery({
    queryKey: ["legal-entities"],
    queryFn: () => api<LegalEntity[]>("/legal-entities?in_scope=true"),
  });
  const jurisdictions = useQuery({
    queryKey: ["jurisdictions"],
    queryFn: () => api<Jurisdiction[]>("/jurisdictions"),
  });
  const profiles = useQuery({
    queryKey: ["profiles", entityId],
    queryFn: () =>
      api<Profile[]>(`/legal-entities/${entityId}/operating-profiles`),
    enabled: !!entityId,
  });
  const assessments = useQuery({
    queryKey: ["assessments"],
    queryFn: () => api<RequirementAssessment[]>("/requirement-assessments"),
  });
  const create = useMutation({
    mutationFn: async () => {
      const result = await api<RequirementAssessment>(
        "/requirement-assessments",
        {
          method: "POST",
          body: JSON.stringify({
            legal_entity_id: entityId,
            operating_profile_id: profileId,
            requested_jurisdictions: jurisdictionIds,
            extra_facts: {},
          }),
        },
      );
      await api(`/requirement-assessments/${result.id}/evaluate`, {
        method: "POST",
      });
      return result;
    },
    onSuccess: () => void assessments.refetch(),
  });
  if (entities.isLoading || jurisdictions.isLoading) return <Loading />;
  if (entities.error || jurisdictions.error)
    return <ErrorState error={entities.error ?? jurisdictions.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Advisory analysis</span>
          <h1>Requirement assessment</h1>
          <p>
            Results require human review and are never presented as definitive
            legal advice.
          </p>
        </div>
      </div>
      <section className="panel assessment-wizard">
        <label>
          Legal entity
          <select
            value={entityId}
            onChange={(e) => {
              setEntityId(e.target.value);
              setProfileId("");
            }}
          >
            <option value="">Select</option>
            {entities.data?.map((row) => (
              <option key={row.id} value={row.id}>
                {row.legal_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Approved operating profile
          <select
            value={profileId}
            onChange={(e) => setProfileId(e.target.value)}
          >
            <option value="">Select</option>
            {profiles.data
              ?.filter((row) => row.status === "ACTIVE")
              .map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} v{row.version}
                </option>
              ))}
          </select>
        </label>
        <fieldset>
          <legend>Jurisdictions</legend>
          <div className="choice-grid">
            {jurisdictions.data?.map((row) => (
              <label key={row.id}>
                <input
                  type="checkbox"
                  checked={jurisdictionIds.includes(row.id)}
                  onChange={(e) =>
                    setJurisdictionIds(
                      e.target.checked
                        ? [...jurisdictionIds, row.id]
                        : jurisdictionIds.filter((id) => id !== row.id),
                    )
                  }
                />
                {row.name}
              </label>
            ))}
          </div>
        </fieldset>
        <button
          disabled={
            !entityId ||
            !profileId ||
            jurisdictionIds.length === 0 ||
            create.isPending
          }
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Evaluating…" : "Create advisory assessment"}
        </button>
      </section>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Assessment</th>
              <th>Status</th>
              <th>Jurisdictions</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {assessments.data?.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/licensing/requirements/${row.id}`}>
                    {row.assessment_key}
                  </Link>
                </td>
                <td>
                  <Status value={row.status} />
                </td>
                <td>{row.requested_jurisdictions.length}</td>
                <td>{new Date(row.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
