import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
