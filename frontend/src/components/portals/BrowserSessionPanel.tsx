import type { PortalBrowserSession } from "../../types";
import { Status } from "../common/States";

type Props = {
  session: PortalBrowserSession | null | undefined;
  hostname: string;
  pending?: boolean;
  onStart: () => void;
  onTakeControl: () => void;
  onReturnControl: () => void;
  onClose: () => void;
};

export function BrowserSessionPanel({
  session,
  hostname,
  pending,
  onStart,
  onTakeControl,
  onReturnControl,
  onClose,
}: Props) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Isolated browser session</h2>
        <Status value={session?.session_status ?? "NOT_STARTED"} />
      </div>
      <dl className="detail-grid">
        <dt>Approved host</dt>
        <dd>{hostname}</dd>
        <dt>Session owner</dt>
        <dd>{session?.operator_user_id ?? "Assigned operator only"}</dd>
        <dt>Expiry</dt>
        <dd>{session ? new Date(session.expires_at).toLocaleString() : "—"}</dd>
      </dl>
      <div className="stacked-actions">
        {!session && (
          <button disabled={pending} onClick={onStart}>
            Start isolated session
          </button>
        )}
        {session?.session_status === "ACTIVE_AUTOMATION" && (
          <button disabled={pending} onClick={onTakeControl}>
            Take human control
          </button>
        )}
        {session?.session_status === "ACTIVE_HUMAN_CONTROL" && (
          <button disabled={pending} onClick={onReturnControl}>
            Return control after verified handoff
          </button>
        )}
        {session && (
          <button className="secondary" disabled={pending} onClick={onClose}>
            Close and destroy profile
          </button>
        )}
      </div>
      <small className="muted">
        Passwords, MFA codes, cookies, tokens, and browser storage are never
        displayed or retained here.
      </small>
    </section>
  );
}
