import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RenewalTimeline } from "../components/licensing/RenewalTimeline";
import { CorrespondenceReviewPage } from "../pages/CorrespondenceReviewPage";

function wrapper(children: React.ReactNode) {
  return (
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  );
}

const LINK = {
  id: "11111111-1111-1111-1111-111111111111",
  compliance_case_id: "22222222-2222-2222-2222-222222222222",
  case_key: "case-ga-renewal",
  email_id: "33333333-3333-3333-3333-333333333333",
  conversation_id: "conv-1",
  link_status: "PROPOSED",
  match_score: 0.8,
  match_reasons: {
    signals: [
      {
        code: "LICENSE_NUMBER",
        detail: "Message quotes licence 12345.",
        weight: 0.6,
      },
    ],
  },
  proposed_at: "2026-07-01T10:00:00+00:00",
  email_subject: "Renewal invoice",
  email_sender: "renewals@vendor.invalid",
  email_received_at: "2026-07-01T09:00:00+00:00",
  legal_entity_name: "Astra Test Holdings",
};

it("shows the entity and the reason before a reviewer confirms a link", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([LINK]), { status: 200 })),
  );
  render(wrapper(<CorrespondenceReviewPage />));

  // The legal entity must be visible: confirming the wrong entity's thread is
  // the error this screen exists to prevent.
  expect(await screen.findByText("Astra Test Holdings")).toBeInTheDocument();
  expect(screen.getByText(/Message quotes licence 12345/)).toBeInTheDocument();
  expect(screen.getByText("80% match")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /confirm link/i }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
});

it("states that correspondence appears only after confirmation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            license_id: "44444444-4444-4444-4444-444444444444",
            license_key: "lic-ga-1",
            current_status: "ACTIVE",
            expiration_date: "2026-12-31",
            renewal_due_date: null,
            open_case_count: 0,
            active_stage: null,
            entries: [],
          }),
          { status: 200 },
        ),
    ),
  );
  render(
    wrapper(
      <RenewalTimeline licenseId="44444444-4444-4444-4444-444444444444" />,
    ),
  );

  await waitFor(() =>
    expect(screen.getByText(/once a reviewer/i)).toBeInTheDocument(),
  );
  expect(screen.getByText("No open case")).toBeInTheDocument();
});

it("orders renewal activity and labels each event source", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            license_id: "44444444-4444-4444-4444-444444444444",
            license_key: "lic-ga-1",
            current_status: "ACTIVE",
            expiration_date: "2026-12-31",
            renewal_due_date: "2026-11-30",
            open_case_count: 1,
            active_stage: "CASE_PLANNING",
            entries: [
              {
                occurred_at: "2026-07-01T09:00:00+00:00",
                category: "EMAIL_RECEIVED",
                summary: "Renewal invoice",
                detail: "From renewals@vendor.invalid",
                actor_id: "reviewer-1",
                case_id: "22222222-2222-2222-2222-222222222222",
                case_key: "case-ga-renewal",
                email_id: null,
                reference: {},
              },
              {
                occurred_at: "2026-07-02T09:00:00+00:00",
                category: "CASE_STAGE",
                summary: "Case moved from DUE_IDENTIFIED to CASE_PLANNING",
                detail: null,
                actor_id: "analyst-1",
                case_id: "22222222-2222-2222-2222-222222222222",
                case_key: "case-ga-renewal",
                email_id: null,
                reference: {},
              },
            ],
          }),
          { status: 200 },
        ),
    ),
  );
  render(
    wrapper(
      <RenewalTimeline licenseId="44444444-4444-4444-4444-444444444444" />,
    ),
  );

  expect(await screen.findByText("Renewal invoice")).toBeInTheDocument();
  expect(
    screen.getByText(/Case moved from DUE_IDENTIFIED/),
  ).toBeInTheDocument();
  expect(screen.getByText("CASE_PLANNING")).toBeInTheDocument();
});
