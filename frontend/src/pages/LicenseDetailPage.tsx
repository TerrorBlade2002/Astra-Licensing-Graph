import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { LicenseRecord } from "../types";

type Event = {
  id: string;
  from_status: string | null;
  to_status: string;
  occurred_at: string;
  note: string | null;
};
export function LicenseDetailPage() {
  const { id = "" } = useParams();
  const license = useQuery({
    queryKey: ["license", id],
    queryFn: () => api<LicenseRecord>(`/licenses/${id}`),
    enabled: !!id,
  });
  const events = useQuery({
    queryKey: ["license-events", id],
    queryFn: () => api<Event[]>(`/licenses/${id}/events`),
    enabled: !!id,
  });
  if (license.isLoading) return <Loading />;
  if (license.error) return <ErrorState error={license.error} />;
  const item = license.data!;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Inventory record</span>
          <h1>{item.license_number ?? item.license_key}</h1>
          <p>Immutable status history and governed source provenance.</p>
        </div>
        <Status value={item.current_status} />
      </div>
      <div className="split">
        <section className="panel detail-list">
          <h2>Core record</h2>
          <dl>
            <dt>Filing channel</dt>
            <dd>{item.filing_channel}</dd>
            <dt>NMLS ID</dt>
            <dd>{item.nmls_license_id ?? "Not recorded"}</dd>
            <dt>Expiration</dt>
            <dd>{item.expiration_date ?? "Not recorded"}</dd>
            <dt>Renewal due</dt>
            <dd>{item.renewal_due_date ?? "Not recorded"}</dd>
            <dt>Owner</dt>
            <dd>{item.responsible_owner ?? "Unassigned"}</dd>
          </dl>
        </section>
        <section className="panel">
          <h2>Status history</h2>
          {events.data?.map((event) => (
            <div className="timeline-row" key={event.id}>
              <Status value={event.to_status} />
              <strong>
                {event.from_status ?? "Created"} → {event.to_status}
              </strong>
              <small>{new Date(event.occurred_at).toLocaleString()}</small>
              <p>{event.note}</p>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
