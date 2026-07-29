import { ApiError } from "../../api/client";
export function Loading({ label = "Loading workspace" }: { label?: string }) {
  return (
    <div className="loading">
      <span />
      <p>{label}…</p>
    </div>
  );
}
export function ErrorState({ error }: { error: unknown }) {
  const e = error as ApiError;
  return (
    <div className="error-state" role="alert">
      <strong>We couldn’t load this view.</strong>
      <p>{e.message}</p>
      {e.correlationId && <code>Correlation {e.correlationId}</code>}
    </div>
  );
}
export function Confidence({ value }: { value: number }) {
  const tone = value >= 0.9 ? "good" : value >= 0.7 ? "warn" : "bad";
  return (
    <span className={`confidence ${tone}`}>{Math.round(value * 100)}%</span>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <span
      className={`status status-${value.toLowerCase().replaceAll("_", "-")}`}
    >
      {value.replaceAll("_", " ")}
    </span>
  );
}
