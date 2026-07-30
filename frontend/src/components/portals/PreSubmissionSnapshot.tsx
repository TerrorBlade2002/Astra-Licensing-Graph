import type { PreSubmissionSnapshot as Snapshot } from "../../types";
import { Status } from "../common/States";

export function PreSubmissionSnapshot({
  snapshot,
  pending,
  onApprove,
  onReject,
}: {
  snapshot: Snapshot;
  pending?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
}) {
  const blockers = snapshot.discrepancy_report.filter(
    (item) => item.blocking !== false,
  );
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Pre-submission snapshot v{snapshot.version}</h2>
        <Status value={snapshot.status} />
      </div>
      <dl className="detail-grid">
        <dt>Fields</dt>
        <dd>{snapshot.field_manifest.length}</dd>
        <dt>Documents</dt>
        <dd>{snapshot.document_manifest.length}</dd>
        <dt>Blocking discrepancies</dt>
        <dd>{blockers.length}</dd>
        <dt>Snapshot hash</dt>
        <dd className="mono">{snapshot.snapshot_sha256}</dd>
      </dl>
      {snapshot.status === "READY_FOR_REVIEW" && onApprove && (
        <div className="stacked-actions">
          <button disabled={pending || blockers.length > 0} onClick={onApprove}>
            Approve exact snapshot
          </button>
          <button className="secondary" disabled={pending} onClick={onReject}>
            Reject
          </button>
        </div>
      )}
    </section>
  );
}
