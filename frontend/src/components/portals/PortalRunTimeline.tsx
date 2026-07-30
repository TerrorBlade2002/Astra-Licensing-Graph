import { Status } from "../common/States";

export type PortalTimelineStep = {
  id: string;
  sequence_number: number;
  step_type: string;
  status: string;
  page_category: string | null;
  result_summary: string | null;
  started_at: string | null;
};

export function PortalRunTimeline({ steps }: { steps: PortalTimelineStep[] }) {
  return (
    <section className="panel">
      <h2>Operator audit timeline</h2>
      {steps.map((step) => (
        <div className="timeline-row" key={step.id}>
          <Status value={step.status} />
          <strong>{step.step_type.replaceAll("_", " ")}</strong>
          <small>{step.page_category ?? "No portal page captured"}</small>
          <p>{step.result_summary}</p>
        </div>
      ))}
    </section>
  );
}
