import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import { PortalCapabilityPanel } from "../components/portals/PortalCapabilityPanel";
import type { PortalDefinition } from "../types";

type Review = {
  id: string;
  version: number;
  status: string;
  reviewed_by_compliance: string | null;
  reviewed_by_security: string | null;
  valid_to: string | null;
};
type Adapter = {
  id: string;
  adapter_key: string;
  version: number;
  status: string;
  test_fixture_version: string | null;
};

const prohibitedActions = {
  ACCEPT_TERMS: true,
  ENTER_MFA: true,
  SOLVE_CAPTCHA: true,
  ATTEST: true,
  SIGN: true,
  ENTER_PAYMENT_CREDENTIALS: true,
  AUTHORIZE_PAYMENT: true,
  FINAL_SUBMIT: true,
};

export function PortalDefinitionPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const [termsReference, setTermsReference] = useState("");
  const [termsHash, setTermsHash] = useState("");
  const portal = useQuery({
    queryKey: ["portal", id],
    queryFn: () => api<PortalDefinition>(`/portals/${id}`),
    enabled: !!id,
  });
  const reviews = useQuery({
    queryKey: ["portal-reviews", id],
    queryFn: () => api<Review[]>(`/portals/${id}/reviews`),
    enabled: !!id,
  });
  const adapters = useQuery({
    queryKey: ["portal-adapters", id],
    queryFn: () => api<Adapter[]>(`/portals/${id}/adapters`),
    enabled: !!id,
  });
  const createReview = useMutation({
    mutationFn: () =>
      api(`/portals/${id}/reviews`, {
        method: "POST",
        body: JSON.stringify({
          terms_reference: termsReference,
          terms_sha256: termsHash,
          allowed_actions: {
            NAVIGATE: true,
            ENTER_FIELD: true,
            UPLOAD_DOCUMENT: true,
            SAVE_DRAFT: true,
            VALIDATE: true,
            CAPTURE_PRE_SUBMISSION: true,
          },
          prohibited_actions: prohibitedActions,
          approved_filing_types: portal.data?.supported_filing_types ?? [],
        }),
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-reviews", id] }),
  });
  const approveReview = useMutation({
    mutationFn: (reviewId: string) =>
      api(`/portal-reviews/${reviewId}/approve`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["portal-reviews", id] });
      void client.invalidateQueries({ queryKey: ["portal", id] });
    },
  });
  const signoffReview = useMutation({
    mutationFn: ({
      reviewId,
      domain,
    }: {
      reviewId: string;
      domain: "compliance" | "security";
    }) =>
      api(`/portal-reviews/${reviewId}/${domain}-signoff`, {
        method: "POST",
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-reviews", id] }),
  });
  const activateAdapter = useMutation({
    mutationFn: (adapterId: string) =>
      api(`/portals/${id}/adapters/${adapterId}/activate`, {
        method: "POST",
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["portal-adapters", id] }),
  });
  if (portal.isLoading) return <Loading />;
  if (portal.error) return <ErrorState error={portal.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">{portal.data!.portal_type}</span>
          <h1>{portal.data!.name}</h1>
          <p>{portal.data!.hostname}</p>
        </div>
        <Status value={portal.data!.status} />
      </div>
      <div className="split">
        <PortalCapabilityPanel portal={portal.data!} />
        <section className="panel">
          <h2>Review versions</h2>
          {reviews.data?.map((review) => (
            <div className="timeline-row" key={review.id}>
              <Status value={review.status} />
              <strong>Version {review.version}</strong>
              <small>
                Compliance: {review.reviewed_by_compliance ?? "Pending"} ·
                Security: {review.reviewed_by_security ?? "Pending"}
              </small>
              {review.status === "DRAFT" && (
                <div className="stacked-actions horizontal">
                  {!review.reviewed_by_compliance && (
                    <button
                      disabled={signoffReview.isPending}
                      onClick={() =>
                        signoffReview.mutate({
                          reviewId: review.id,
                          domain: "compliance",
                        })
                      }
                    >
                      Record compliance sign-off
                    </button>
                  )}
                  {!review.reviewed_by_security && (
                    <button
                      disabled={signoffReview.isPending}
                      onClick={() =>
                        signoffReview.mutate({
                          reviewId: review.id,
                          domain: "security",
                        })
                      }
                    >
                      Record security sign-off
                    </button>
                  )}
                  <button
                    disabled={
                      approveReview.isPending ||
                      !review.reviewed_by_compliance ||
                      !review.reviewed_by_security
                    }
                    onClick={() => approveReview.mutate(review.id)}
                  >
                    Approve reviewed version
                  </button>
                </div>
              )}
            </div>
          ))}
        </section>
      </div>
      <div className="split">
        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            createReview.mutate();
          }}
        >
          <h2>Create terms and automation review</h2>
          <label>
            Governed terms reference
            <input
              value={termsReference}
              onChange={(event) => setTermsReference(event.target.value)}
            />
          </label>
          <label>
            Terms SHA-256
            <input
              value={termsHash}
              onChange={(event) => setTermsHash(event.target.value)}
            />
          </label>
          <button
            disabled={
              createReview.isPending ||
              !termsReference ||
              !/^[a-f0-9]{64}$/i.test(termsHash)
            }
          >
            Save draft review
          </button>
        </form>
        <section className="panel">
          <h2>Versioned adapters</h2>
          {adapters.data?.map((adapter) => (
            <div className="timeline-row" key={adapter.id}>
              <Status value={adapter.status} />
              <strong>
                {adapter.adapter_key} v{adapter.version}
              </strong>
              <small>
                Fixture {adapter.test_fixture_version ?? "not recorded"}
              </small>
              {adapter.status !== "ACTIVE" && (
                <button
                  disabled={activateAdapter.isPending}
                  onClick={() => activateAdapter.mutate(adapter.id)}
                >
                  Activate reviewed adapter
                </button>
              )}
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
