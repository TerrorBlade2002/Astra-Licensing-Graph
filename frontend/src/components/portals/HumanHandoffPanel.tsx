import type { PortalHandoff } from "../../types";
import { Status } from "../common/States";

export function HumanHandoffPanel({
  handoffs,
  pending,
  onAccept,
}: {
  handoffs: PortalHandoff[];
  pending?: boolean;
  onAccept: (id: string) => void;
}) {
  return (
    <section className="panel">
      <h2>Human handoffs</h2>
      {handoffs.length === 0 && <p className="muted">No active handoff.</p>}
      {handoffs.map((handoff) => (
        <article className="handoff-card" key={handoff.id}>
          <div className="panel-heading">
            <strong>{handoff.handoff_type.replaceAll("_", " ")}</strong>
            <Status value={handoff.status} />
          </div>
          <p>
            Automation stopped because this action must be performed by the
            assigned authorized person. Complete only this action; do not share
            another user’s portal session.
          </p>
          <small>
            Completion is accepted only after the resulting portal state or
            governed evidence is verified.
          </small>
          {handoff.status === "REQUESTED" && (
            <button disabled={pending} onClick={() => onAccept(handoff.id)}>
              Accept assigned handoff
            </button>
          )}
        </article>
      ))}
    </section>
  );
}
