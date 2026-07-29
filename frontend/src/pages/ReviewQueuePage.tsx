import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import {
  Confidence,
  ErrorState,
  Loading,
  Status,
} from "../components/common/States";
import type { ReviewItem } from "../types";

export function ReviewQueuePage() {
  const [status, setStatus] = useState("PENDING");
  const [vendor, setVendor] = useState("");
  const query = useQuery({
    queryKey: ["reviews", status, vendor],
    queryFn: () =>
      api<ReviewItem[]>(
        `/classification-reviews?status=${status}&vendor=${vendor}`,
      ),
  });
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Human-in-the-loop</span>
          <h1>Classification review</h1>
          <p>
            Compare machine proposals with source evidence before work advances.
          </p>
        </div>
        <div className="queue-count">
          <strong>{query.data?.length ?? "—"}</strong>
          <span>in this view</span>
        </div>
      </div>
      <section className="toolbar" aria-label="Queue filters">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option>PENDING</option>
            <option>IN_REVIEW</option>
            <option>APPROVED</option>
            <option>CORRECTED</option>
            <option>REJECTED</option>
          </select>
        </label>
        <label>
          Vendor
          <select value={vendor} onChange={(e) => setVendor(e.target.value)}>
            <option value="">All vendors</option>
            <option>RASI</option>
            <option>NMLS</option>
          </select>
        </label>
        <div className="toolbar-note">
          <span className="status-dot" />
          Live from the review API
        </div>
      </section>
      {query.isLoading ? (
        <Loading label="Loading review queue" />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : query.data?.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">✓</div>
          <h2>This queue is clear</h2>
          <p>No classifications match the current filters.</p>
          <button
            className="secondary"
            onClick={() => {
              setStatus("");
              setVendor("");
            }}
          >
            Show all reviews
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Correspondence</th>
                <th>Classification</th>
                <th>Jurisdiction</th>
                <th>Due</th>
                <th>Confidence</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {query.data?.map((item) => (
                <tr key={item.review.id}>
                  <td>
                    {item.received_at
                      ? new Date(item.received_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td>
                    <strong>{item.subject || "No subject"}</strong>
                    <small>{item.sender || "Unknown sender"}</small>
                  </td>
                  <td>
                    <span className="vendor">
                      {item.classification.vendor || "Unknown"}
                    </span>
                    {item.classification.email_type.replaceAll("_", " ")}
                  </td>
                  <td>{item.classification.states.join(", ") || "—"}</td>
                  <td>{item.classification.due_date || "—"}</td>
                  <td>
                    <Confidence value={item.classification.confidence} />
                  </td>
                  <td>
                    <Status value={item.review.decision} />
                  </td>
                  <td>
                    <Link
                      className="row-link"
                      to={`/reviews/${item.review.classification_id}`}
                    >
                      Review →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
