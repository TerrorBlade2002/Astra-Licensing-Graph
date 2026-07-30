import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CurrentTrackerPage } from "../pages/CurrentTrackerPage";
import { LicensingDashboardPage } from "../pages/LicensingDashboardPage";
import { PacketBuilderPage } from "../pages/PacketBuilderPage";

function wrapper(children: React.ReactNode, initialEntries = ["/"]) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false } },
          })
        }
      >
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  );
}

it("labels requirement operations as advisory and human-reviewed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith("/blocked-cases")
        ? []
        : {
            advisory_notice:
              "Advisory operational result only; human review is required.",
            licenses_total: 2,
            licenses_active: 1,
            licenses_expiring: { "30": 1 },
            obligations_overdue: 0,
            cases_open: 1,
            cases_blocked: 0,
            cases_overdue: 0,
            cases_by_stage: { REQUIREMENTS_REVIEWED: 1 },
            information_requests_open: 0,
            information_values_stale: 0,
            forms_waiting_signature: 0,
            forms_waiting_information: 0,
            packets_missing_items: 0,
            sources_stale: 0,
            source_changes_pending: 0,
            assessments_counsel_review: 0,
          };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(wrapper(<LicensingDashboardPage />));

  expect(
    await screen.findByText(/Advisory operational result only/i),
  ).toBeInTheDocument();
  expect(screen.getByText("REQUIREMENTS REVIEWED")).toBeInTheDocument();
});

it("filters the current tracker by time and keeps non-licensed states separate", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      const body = {
        metadata: {
          source_workbook: "Main License Book.xlsx",
          source_last_modified_at: "2026-07-30T15:52:38+00:00",
          source_sheets: ["DB", "Non Licensed States"],
          db_rows: 67,
          tracked_jurisdictions: 63,
          data_minimization: "Identifiers excluded.",
        },
        as_of: "2026-07-30",
        selected_window: "ALL",
        available_windows: [
          { value: "NEXT_90", label: "Next 3 months" },
          { value: "NEXT_YEAR", label: "Next year" },
        ],
        summary: {
          events_total: 2,
          due_next_30: 0,
          due_next_90: 1,
          due_this_year: 1,
          overdue: 0,
          non_licensed: 1,
          tracked_jurisdictions: 63,
        },
        events: [
          {
            event_id: "db-2-license",
            state: "Alabama",
            abbreviation: "AL",
            jurisdiction_type: "State",
            tracker_status: "Licensed",
            item_type: "LICENSE",
            item_name: "License renewal",
            due_date: "2026-09-30",
            agency: "Rasi",
            owner: null,
            notes: null,
            source_row: 2,
            source_cell: "DB!G2",
            days_remaining: 62,
            timing_status: "UPCOMING",
          },
          {
            event_id: "db-3-bond",
            state: "Alaska",
            abbreviation: "AK",
            jurisdiction_type: "State",
            tracker_status: "Licensed",
            item_type: "BOND",
            item_name: "Bond renewal",
            due_date: "2027-04-26",
            agency: "Cornerstone",
            owner: null,
            notes: null,
            source_row: 3,
            source_cell: "DB!N3",
            days_remaining: 270,
            timing_status: "FUTURE",
          },
        ],
        non_licensed: [
          {
            record_id: "db-66-not-licensed",
            state: "American Samoa",
            abbreviation: null,
            jurisdiction_type: "UT",
            nmls: "No",
            reason: "Gathering More Information",
            comments: null,
            source_row: 66,
          },
        ],
      };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(wrapper(<CurrentTrackerPage />, ["/licensing/tracker"]));

  expect(await screen.findByText("Alabama")).toBeInTheDocument();
  expect(screen.queryByText("Alaska")).not.toBeInTheDocument();
  expect(screen.getByText("American Samoa")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Next year" }));
  expect(screen.getByText("Alaska")).toBeInTheDocument();
  expect(screen.queryByText("Alabama")).not.toBeInTheDocument();
});

it("does not allow packet approval before the governed archive is ready", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith("/document-packets")
        ? [
            {
              id: "packet-1",
              packet_key: "SYNTHETIC-packet-1",
              compliance_case_id: "case-1",
              version: 1,
              status: "READY_FOR_REVIEW",
              manifest_sha256: "a".repeat(64),
            },
          ]
        : {
            id: "packet-1",
            packet_key: "SYNTHETIC-packet-1",
            compliance_case_id: "case-1",
            version: 1,
            status: "READY_FOR_REVIEW",
            manifest_sha256: "a".repeat(64),
            archive_ready: false,
            archive_sha256: null,
            archive_size_bytes: null,
            missing_items: [],
            validation_results: [],
            items: [],
          };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(wrapper(<PacketBuilderPage />, ["/?packet=packet-1"]));

  expect(
    await screen.findByText(/retrieving and hash-checking/i),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Approve immutable packet/i }),
  ).toBeDisabled();
});
