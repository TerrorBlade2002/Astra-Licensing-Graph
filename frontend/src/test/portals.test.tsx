import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PortalHandoffPage } from "../pages/PortalHandoffPage";
import { PortalRegistryPage } from "../pages/PortalRegistryPage";

function wrapper(children: React.ReactNode, initialEntry: string) {
  return (
    <MemoryRouter initialEntries={[initialEntry]}>
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

it("shows portal governance state without credential controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify([
            {
              id: "portal-1",
              portal_key: "synthetic",
              name: "Synthetic filing portal",
              portal_type: "OTHER",
              base_url: "https://portal.example.invalid",
              hostname: "portal.example.invalid",
              supported_filing_types: ["RENEWAL"],
              approved_automation_level: "PRE_SUBMISSION_ASSIST",
              status: "APPROVED_ASSISTED",
              data_classification: "CONFIDENTIAL",
              credential_model: "INDIVIDUAL_USER_LOGIN",
              mfa_model: "HUMAN",
              captcha_expected: true,
              terms_review_required: true,
              terms_review_expires_at: "2030-01-01T00:00:00Z",
              final_submit_human_only: true,
              payment_human_only: true,
              attestation_human_only: true,
              signature_human_only: true,
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );

  render(wrapper(<PortalRegistryPage />, "/portals"));

  expect(
    await screen.findByText("Synthetic filing portal"),
  ).toBeInTheDocument();
  expect(screen.getByText("PRE SUBMISSION ASSIST")).toBeInTheDocument();
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/MFA code/i)).not.toBeInTheDocument();
});

it("routes final submission to dedicated human evidence controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            id: "handoff-1",
            portal_run_id: "run-1",
            browser_session_id: null,
            handoff_type: "FINAL_SUBMIT",
            status: "ACTIVE",
            requested_from_user_id: "user-1",
            requested_at: "2030-01-01T00:00:00Z",
            accepted_at: "2030-01-01T00:01:00Z",
            completed_at: null,
            result: null,
            operator_confirmation: null,
            evidence_reference: null,
            expires_at: "2030-01-01T01:00:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );

  render(
    wrapper(
      <Routes>
        <Route path="/portal-handoffs/:id" element={<PortalHandoffPage />} />
      </Routes>,
      "/portal-handoffs/handoff-1",
    ),
  );

  expect(
    await screen.findByText(
      /cannot be completed by a generic browser confirmation/i,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /Open governed evidence controls/i }),
  ).toHaveAttribute("href", "/portal-runs/run-1/submission-evidence");
  expect(
    screen.queryByRole("button", {
      name: /Request portal-state verification/i,
    }),
  ).not.toBeInTheDocument();
});
