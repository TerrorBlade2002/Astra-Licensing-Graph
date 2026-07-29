import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { RoleGuard } from "../auth/RoleGuard";
import { ErrorState, Loading } from "../components/common/States";

type RecipientPolicy = {
  id: string;
  rule_key: string;
  rule_type: string;
  priority: number;
  action: string;
  enabled: boolean;
  reason: string | null;
};

export function AdminRulesPage() {
  const q = useQuery({
    queryKey: ["taxonomy-and-recipient-policies"],
    queryFn: async () => ({
      vendors: await api<string[]>("/taxonomy/vendors"),
      types: await api<string[]>("/taxonomy/email-types"),
      routes: await api<string[]>("/taxonomy/destination-folders"),
      recipientPolicies: await api<RecipientPolicy[]>(
        "/admin/recipient-policies",
      ),
    }),
  });

  return (
    <RoleGuard role="Licensing.Admin">
      <main>
        <div className="page-title">
          <div>
            <span className="eyebrow">Admin · immutable configuration</span>
            <h1>Rule studio</h1>
            <p>
              Inspect versioned deterministic classification and controlled
              recipient rules.
            </p>
          </div>
        </div>
        {q.isLoading ? (
          <Loading />
        ) : q.error ? (
          <ErrorState error={q.error} />
        ) : (
          <div className="admin-grid">
            <section className="panel">
              <span className="eyebrow">Active taxonomy</span>
              <h2>astra-default · v1</h2>
              <p>
                Verified sender identity has precedence over body mentions.
                Specific request rules outrank renewal context.
              </p>
              <div className="version-line">
                <b>ACTIVE</b>
                <span>Evaluation required before replacement</span>
              </div>
            </section>
            <section className="panel">
              <h2>Registry coverage</h2>
              <dl className="detail-list">
                <div>
                  <dt>Known vendors</dt>
                  <dd>{q.data?.vendors.length}</dd>
                </div>
                <div>
                  <dt>Email types</dt>
                  <dd>{q.data?.types.length}</dd>
                </div>
                <div>
                  <dt>Controlled routes</dt>
                  <dd>{q.data?.routes.length}</dd>
                </div>
              </dl>
            </section>
            <section className="panel full">
              <h2>Classification rule families</h2>
              <div className="rule-list">
                {[
                  "Verified sender and domain",
                  "Requested information extraction",
                  "Canonical jurisdiction",
                  "License phrases and numbers",
                  "Explicit deadline",
                  "Destination routing",
                ].map((rule, index) => (
                  <div key={rule}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{rule}</strong>
                    <b>Enabled</b>
                  </div>
                ))}
              </div>
            </section>
            <section className="panel full">
              <span className="eyebrow">Controlled communications</span>
              <h2>Recipient policy registry</h2>
              <p>
                These rules are re-evaluated during review, send approval, and
                immediately before Mail.Send.
              </p>
              <div className="rule-list">
                {q.data?.recipientPolicies.map((policy) => (
                  <div key={policy.id}>
                    <span>{String(policy.priority).padStart(2, "0")}</span>
                    <strong>
                      {policy.rule_key} · {policy.rule_type}
                    </strong>
                    <b>{policy.enabled ? policy.action : "Disabled"}</b>
                  </div>
                ))}
                {q.data?.recipientPolicies.length === 0 && (
                  <p>
                    No database policies are configured. Fail-closed limits,
                    reply-all review, and default BCC controls remain active.
                  </p>
                )}
              </div>
            </section>
          </div>
        )}
      </main>
    </RoleGuard>
  );
}
