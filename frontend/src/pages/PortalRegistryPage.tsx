import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { PortalDefinition } from "../types";

export function PortalRegistryPage() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const portals = useQuery({
    queryKey: ["portals"],
    queryFn: () => api<PortalDefinition[]>("/portals"),
  });
  const create = useMutation({
    mutationFn: () =>
      api<PortalDefinition>("/portals", {
        method: "POST",
        body: JSON.stringify({
          portal_key: key,
          name,
          portal_type: "OTHER",
          base_url: baseUrl,
          supported_filing_types: [],
          approved_automation_level: "PREPARE_ONLY",
          data_classification: "CONFIDENTIAL",
          credential_model: "UNKNOWN",
        }),
      }),
    onSuccess: () => {
      setName("");
      setKey("");
      setBaseUrl("");
      void client.invalidateQueries({ queryKey: ["portals"] });
    },
  });
  if (portals.isLoading) return <Loading />;
  if (portals.error) return <ErrorState error={portals.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Governed assistance</span>
          <h1>Portal registry</h1>
          <p>
            Every portal starts disabled and requires current compliance,
            security, terms, entity, filing-type, and adapter approval.
          </p>
        </div>
      </div>
      <section className="panel wide">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Portal</th>
                <th>Type</th>
                <th>Host</th>
                <th>Automation</th>
                <th>MFA / CAPTCHA</th>
                <th>Terms review</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {portals.data?.map((portal) => (
                <tr key={portal.id}>
                  <td>
                    <Link to={`/portals/${portal.id}`}>{portal.name}</Link>
                  </td>
                  <td>{portal.portal_type}</td>
                  <td>{portal.hostname}</td>
                  <td>
                    <Status value={portal.approved_automation_level} />
                  </td>
                  <td>
                    {portal.mfa_model ?? "—"} /{" "}
                    {portal.captcha_expected ? "Human" : "No"}
                  </td>
                  <td>
                    {portal.terms_review_expires_at
                      ? new Date(
                          portal.terms_review_expires_at,
                        ).toLocaleDateString()
                      : "Pending"}
                  </td>
                  <td>
                    <Status value={portal.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <h2>Register discovered portal</h2>
        <label>
          Portal name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Stable key
          <input value={key} onChange={(event) => setKey(event.target.value)} />
        </label>
        <label>
          Approved HTTPS base URL
          <input
            type="url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
        <button disabled={create.isPending || !name || !key || !baseUrl}>
          Register for review
        </button>
        {create.error && <ErrorState error={create.error} />}
      </form>
    </main>
  );
}
