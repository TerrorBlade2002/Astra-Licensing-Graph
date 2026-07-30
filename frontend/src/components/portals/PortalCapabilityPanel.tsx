import type { PortalDefinition } from "../../types";
import { Status } from "../common/States";

export function PortalCapabilityPanel({
  portal,
}: {
  portal: PortalDefinition;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Approved capability</h2>
        <Status value={portal.status} />
      </div>
      <dl className="detail-grid">
        <dt>Automation</dt>
        <dd>{portal.approved_automation_level}</dd>
        <dt>Credential model</dt>
        <dd>{portal.credential_model}</dd>
        <dt>MFA</dt>
        <dd>{portal.mfa_model ?? "Not recorded"}</dd>
        <dt>CAPTCHA expected</dt>
        <dd>{portal.captcha_expected ? "Human handoff" : "No"}</dd>
        <dt>Terms review expires</dt>
        <dd>
          {portal.terms_review_expires_at
            ? new Date(portal.terms_review_expires_at).toLocaleDateString()
            : "Not recorded"}
        </dd>
      </dl>
      <p className="safety-callout">
        Attestation, signature, payment, terms acceptance, and final submission
        are human-only.
      </p>
    </section>
  );
}
