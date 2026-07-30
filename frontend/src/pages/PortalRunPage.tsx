import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import { BrowserSessionPanel } from "../components/portals/BrowserSessionPanel";
import { DocumentUploadStatus } from "../components/portals/DocumentUploadStatus";
import { HumanHandoffPanel } from "../components/portals/HumanHandoffPanel";
import { PortalFieldComparison } from "../components/portals/PortalFieldComparison";
import {
  PortalRunTimeline,
  type PortalTimelineStep,
} from "../components/portals/PortalRunTimeline";
import type {
  PortalBrowserSession,
  PortalDefinition,
  PortalHandoff,
  PortalRun,
  PortalRunDocument,
  PortalRunField,
  PreSubmissionSnapshot,
} from "../types";

export function PortalRunPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [routeKey, setRouteKey] = useState("");
  const run = useQuery({
    queryKey: ["portal-run", id],
    queryFn: () => api<PortalRun>(`/portal-runs/${id}`),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const portal = useQuery({
    queryKey: ["portal", run.data?.portal_definition_id],
    queryFn: () =>
      api<PortalDefinition>(`/portals/${run.data!.portal_definition_id}`),
    enabled: !!run.data?.portal_definition_id,
  });
  const browser = useQuery({
    queryKey: ["portal-browser", id],
    queryFn: () =>
      api<PortalBrowserSession | null>(`/portal-runs/${id}/browser-session`),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const handoffs = useQuery({
    queryKey: ["portal-handoffs", id],
    queryFn: () => api<PortalHandoff[]>(`/portal-runs/${id}/handoffs`),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const fields = useQuery({
    queryKey: ["portal-fields", id],
    queryFn: () => api<PortalRunField[]>(`/portal-runs/${id}/fields`),
    enabled: !!id,
  });
  const documents = useQuery({
    queryKey: ["portal-documents", id],
    queryFn: () => api<PortalRunDocument[]>(`/portal-runs/${id}/documents`),
    enabled: !!id,
  });
  const timeline = useQuery({
    queryKey: ["portal-timeline", id],
    queryFn: () => api<PortalTimelineStep[]>(`/portal-runs/${id}/timeline`),
    enabled: !!id,
  });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["portal-run", id] });
    void client.invalidateQueries({ queryKey: ["portal-browser", id] });
    void client.invalidateQueries({ queryKey: ["portal-handoffs", id] });
    void client.invalidateQueries({ queryKey: ["portal-fields", id] });
    void client.invalidateQueries({ queryKey: ["portal-documents", id] });
    void client.invalidateQueries({ queryKey: ["portal-timeline", id] });
  };
  const action = useMutation({
    mutationFn: (path: string) =>
      api(`/portal-runs/${id}/${path}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const sessionAction = useMutation({
    mutationFn: ({ sessionId, path }: { sessionId: string; path: string }) =>
      api(`/browser-sessions/${sessionId}/${path}`, {
        method: "POST",
      }),
    onSuccess: refresh,
  });
  const startSession = useMutation({
    mutationFn: () =>
      api(`/portal-runs/${id}/browser-session`, { method: "POST" }),
    onSuccess: refresh,
  });
  const navigatePortal = useMutation({
    mutationFn: () =>
      api(`/portal-runs/${id}/navigate`, {
        method: "POST",
        body: JSON.stringify({
          route_key: routeKey,
          request_id: crypto.randomUUID(),
        }),
      }),
    onSuccess: refresh,
  });
  const acceptHandoff = useMutation({
    mutationFn: (handoffId: string) =>
      api(`/handoffs/${handoffId}/accept`, { method: "POST" }),
    onSuccess: refresh,
  });
  const snapshot = useMutation({
    mutationFn: () =>
      api<PreSubmissionSnapshot>(`/portal-runs/${id}/pre-submission-snapshot`, {
        method: "POST",
      }),
    onSuccess: (created) => navigate(`/pre-submission-snapshots/${created.id}`),
  });
  const finalHandoff = useMutation({
    mutationFn: () =>
      api<PortalHandoff>(`/portal-runs/${id}/request-final-submit-handoff`, {
        method: "POST",
      }),
    onSuccess: (created) => navigate(`/portal-handoffs/${created.id}`),
  });
  if (run.isLoading) return <Loading />;
  if (run.error) return <ErrorState error={run.error} />;
  const item = run.data!;
  const pending =
    action.isPending ||
    sessionAction.isPending ||
    startSession.isPending ||
    acceptHandoff.isPending;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">{item.automation_level}</span>
          <h1>{item.run_key}</h1>
          <p>
            {item.filing_type} · Case {item.compliance_case_id}
          </p>
        </div>
        <Status value={item.status} />
      </div>
      {item.last_error_message && (
        <div className="safety-callout">
          {item.last_error_code}: {item.last_error_message}
        </div>
      )}
      <div className="stacked-actions horizontal">
        <button disabled={pending} onClick={() => action.mutate("start")}>
          Start governed run
        </button>
        <label>
          Reviewed route key
          <input
            value={routeKey}
            onChange={(event) => setRouteKey(event.target.value)}
            placeholder="renewal-filing"
          />
        </label>
        <button
          disabled={pending || navigatePortal.isPending || !routeKey}
          onClick={() => navigatePortal.mutate()}
        >
          Navigate reviewed route
        </button>
        <button
          disabled={pending}
          onClick={() => action.mutate("enter-approved-fields")}
        >
          Enter reviewed fields
        </button>
        <button
          disabled={pending}
          onClick={() => action.mutate("upload-approved-documents")}
        >
          Upload approved packet
        </button>
        <button disabled={pending} onClick={() => action.mutate("validate")}>
          Capture portal validation
        </button>
        <button disabled={snapshot.isPending} onClick={() => snapshot.mutate()}>
          Capture pre-submission snapshot
        </button>
        <button
          disabled={
            finalHandoff.isPending || item.status !== "PRE_SUBMISSION_APPROVED"
          }
          onClick={() => finalHandoff.mutate()}
        >
          Request human final-submit handoff
        </button>
      </div>
      <div className="split">
        <BrowserSessionPanel
          session={browser.data}
          hostname={portal.data?.hostname ?? "Approved host loading…"}
          pending={pending}
          onStart={() => startSession.mutate()}
          onTakeControl={() =>
            browser.data &&
            sessionAction.mutate({
              sessionId: browser.data.id,
              path: "take-control",
            })
          }
          onReturnControl={() =>
            browser.data &&
            sessionAction.mutate({
              sessionId: browser.data.id,
              path: "return-control",
            })
          }
          onClose={() =>
            browser.data &&
            sessionAction.mutate({
              sessionId: browser.data.id,
              path: "close?reason=Operator%20closed",
            })
          }
        />
        <HumanHandoffPanel
          handoffs={
            handoffs.data?.filter((handoff) =>
              ["REQUESTED", "ACCEPTED", "ACTIVE"].includes(handoff.status),
            ) ?? []
          }
          pending={acceptHandoff.isPending}
          onAccept={(handoffId) => acceptHandoff.mutate(handoffId)}
        />
      </div>
      <PortalFieldComparison fields={fields.data ?? []} />
      <DocumentUploadStatus documents={documents.data ?? []} />
      <PortalRunTimeline steps={timeline.data ?? []} />
      <div className="stacked-actions horizontal">
        <button
          className="secondary"
          onClick={() => navigate(`/portal-runs/${id}/submission-evidence`)}
        >
          Submission evidence
        </button>
        <button
          className="secondary"
          disabled={pending}
          onClick={() =>
            action.mutate(item.status === "BLOCKED" ? "resume" : "pause")
          }
        >
          {item.status === "BLOCKED" ? "Resume safely" : "Pause"}
        </button>
        <button
          className="secondary"
          disabled={pending}
          onClick={() => action.mutate("cancel")}
        >
          Cancel
        </button>
      </div>
      {(action.error ||
        sessionAction.error ||
        startSession.error ||
        snapshot.error ||
        navigatePortal.error ||
        finalHandoff.error) && (
        <ErrorState
          error={
            action.error ??
            sessionAction.error ??
            startSession.error ??
            snapshot.error ??
            navigatePortal.error ??
            finalHandoff.error
          }
        />
      )}
    </main>
  );
}
