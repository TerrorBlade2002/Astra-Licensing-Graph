import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type {
  CurrentTracker,
  CurrentTrackerEvent,
  NonLicensedTrackerState,
} from "../types";

const ITEM_TYPES = [
  ["ALL", "All requirements"],
  ["LICENSE", "Licenses"],
  ["BOND", "Bonds"],
  ["ANNUAL_REPORT", "Annual reports"],
  ["OTHER_DOCUMENT", "Other filings"],
] as const;

const ITEM_LABELS: Record<string, string> = {
  LICENSE: "License",
  BOND: "Bond",
  ANNUAL_REPORT: "Annual report",
  OTHER_DOCUMENT: "Other filing",
};

function inWindow(event: CurrentTrackerEvent, window: string, asOf: string) {
  if (window === "NEXT_30")
    return event.days_remaining >= 0 && event.days_remaining <= 30;
  if (window === "NEXT_90")
    return event.days_remaining >= 0 && event.days_remaining <= 90;
  if (window === "THIS_YEAR")
    return (
      event.days_remaining >= 0 &&
      event.due_date.slice(0, 4) === asOf.slice(0, 4)
    );
  if (window === "NEXT_YEAR")
    return Number(event.due_date.slice(0, 4)) === Number(asOf.slice(0, 4)) + 1;
  if (window === "ALL_FUTURE") return event.days_remaining >= 0;
  if (window === "OVERDUE") return event.days_remaining < 0;
  return true;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value.slice(0, 10)}T00:00:00Z`));
}

function eventMatches(event: CurrentTrackerEvent, query: string) {
  if (!query) return true;
  return [
    event.state,
    event.abbreviation,
    event.item_name,
    event.agency,
    event.owner,
    event.tracker_status,
  ]
    .filter(Boolean)
    .some((value) => value!.toLocaleLowerCase().includes(query));
}

function stateMatches(state: NonLicensedTrackerState, query: string) {
  if (!query) return true;
  return [
    state.state,
    state.abbreviation,
    state.reason,
    state.comments,
    state.jurisdiction_type,
  ]
    .filter(Boolean)
    .some((value) => value!.toLocaleLowerCase().includes(query));
}

export function CurrentTrackerPage() {
  const [window, setWindow] = useState("NEXT_90");
  const [itemType, setItemType] = useState("ALL");
  const [search, setSearch] = useState("");
  const [stateSearch, setStateSearch] = useState("");
  const query = useQuery({
    queryKey: ["current-tracker"],
    queryFn: () =>
      api<CurrentTracker>("/licensing-dashboard/current-tracker?window=ALL"),
  });

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const normalizedStateSearch = stateSearch.trim().toLocaleLowerCase();
  const events = useMemo(
    () =>
      (query.data?.events ?? []).filter(
        (event) =>
          inWindow(event, window, query.data?.as_of ?? "") &&
          (itemType === "ALL" || event.item_type === itemType) &&
          eventMatches(event, normalizedSearch),
      ),
    [itemType, normalizedSearch, query.data, window],
  );
  const nonLicensed = useMemo(
    () =>
      (query.data?.non_licensed ?? []).filter((state) =>
        stateMatches(state, normalizedStateSearch),
      ),
    [normalizedStateSearch, query.data],
  );

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  const tracker = query.data!;

  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Current operational tracker</span>
          <h1>Renewals and filing calendar</h1>
          <p>
            Built only from the maintained DB and Non Licensed States sheets.
          </p>
        </div>
        <div className="tracker-source">
          <strong>{tracker.metadata.source_workbook}</strong>
          <span>
            Updated{" "}
            {formatDate(tracker.metadata.source_last_modified_at.slice(0, 10))}
          </span>
        </div>
      </div>

      <section className="metrics tracker-metrics">
        <div>
          <strong>{tracker.summary.due_next_30}</strong>
          <span>Due in 30 days</span>
        </div>
        <div>
          <strong>{tracker.summary.due_next_90}</strong>
          <span>Due in 3 months</span>
        </div>
        <div>
          <strong>{tracker.summary.due_this_year}</strong>
          <span>Due this year</span>
        </div>
        <div>
          <strong>{tracker.summary.overdue}</strong>
          <span>Past tracker date</span>
        </div>
        <div>
          <strong>{tracker.summary.non_licensed}</strong>
          <span>Non-licensed</span>
        </div>
        <div>
          <strong>{tracker.summary.tracked_jurisdictions}</strong>
          <span>Tracked jurisdictions</span>
        </div>
      </section>

      <section className="panel tracker-panel">
        <div className="panel-title">
          <div>
            <span className="eyebrow">Upcoming requirements</span>
            <h2>{events.length} matching tracker items</h2>
          </div>
          <small>As of {formatDate(tracker.as_of)}</small>
        </div>

        <div className="tracker-window-buttons" aria-label="Time window">
          {tracker.available_windows.map((option) => (
            <button
              type="button"
              key={option.value}
              aria-pressed={window === option.value}
              onClick={() => setWindow(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="toolbar tracker-toolbar">
          <label>
            Requirement
            <select
              value={itemType}
              onChange={(event) => setItemType(event.target.value)}
            >
              {ITEM_TYPES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="tracker-search">
            Search
            <input
              type="search"
              placeholder="State, agency, owner…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <span className="toolbar-note">
            Dates remain tied to their source DB cell.
          </span>
        </div>

        <div className="table-wrap tracker-table">
          <table>
            <thead>
              <tr>
                <th>Jurisdiction</th>
                <th>Requirement</th>
                <th>Due date</th>
                <th>Timing</th>
                <th>Responsibility</th>
                <th>Tracker status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id}>
                  <td>
                    <strong>{event.state}</strong>
                    <small>
                      {[event.abbreviation, event.jurisdiction_type]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </td>
                  <td>
                    <span className="vendor">
                      {ITEM_LABELS[event.item_type] ?? event.item_type}
                    </span>
                    <strong>{event.item_name}</strong>
                    <small>{event.source_cell}</small>
                  </td>
                  <td>
                    <strong>{formatDate(event.due_date)}</strong>
                  </td>
                  <td>
                    <span
                      className={`tracker-due tracker-due-${event.timing_status.toLocaleLowerCase()}`}
                    >
                      {event.days_remaining < 0
                        ? `${Math.abs(event.days_remaining)} days past`
                        : event.days_remaining === 0
                          ? "Due today"
                          : `${event.days_remaining} days`}
                    </span>
                  </td>
                  <td>
                    <strong>
                      {event.owner ?? event.agency ?? "Not specified"}
                    </strong>
                    {event.owner && event.agency && (
                      <small>{event.agency}</small>
                    )}
                  </td>
                  <td>
                    <Status value={event.tracker_status ?? "UNKNOWN"} />
                  </td>
                </tr>
              ))}
              {!events.length && (
                <tr>
                  <td colSpan={6} className="tracker-empty">
                    No tracker items match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel tracker-panel non-licensed-panel">
        <div className="panel-title">
          <div>
            <span className="eyebrow">Separate review queue</span>
            <h2>Non-licensed states and territories</h2>
          </div>
          <strong>{nonLicensed.length} shown</strong>
        </div>
        <div className="toolbar tracker-toolbar">
          <label className="tracker-search">
            Search non-licensed records
            <input
              type="search"
              placeholder="State, reason, comment…"
              value={stateSearch}
              onChange={(event) => setStateSearch(event.target.value)}
            />
          </label>
          <span className="toolbar-note">
            Includes every current Not Licensed row in DB.
          </span>
        </div>
        <div className="non-licensed-grid">
          {nonLicensed.map((state) => (
            <article key={state.record_id}>
              <header>
                <div>
                  <strong>{state.state}</strong>
                  <small>
                    {[state.abbreviation, state.jurisdiction_type]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </div>
                <Status value="NOT LICENSED" />
              </header>
              <dl>
                <div>
                  <dt>Reason</dt>
                  <dd>{state.reason ?? "Reason not specified"}</dd>
                </div>
                <div>
                  <dt>NMLS</dt>
                  <dd>{state.nmls ?? "Not specified"}</dd>
                </div>
              </dl>
              {state.comments && <p>{state.comments}</p>}
              <small className="tracker-source-row">
                Source: DB row {state.source_row}
              </small>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
