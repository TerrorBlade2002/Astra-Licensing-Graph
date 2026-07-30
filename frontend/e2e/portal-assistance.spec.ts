import { expect, test } from "@playwright/test";

test("Milestone 7 stops before human final submission", async ({ page }) => {
  const runId = "00000000-0000-0000-0000-000000000071";
  const portalId = "00000000-0000-0000-0000-000000000072";
  const finalActionRequests: string[] = [];
  page.on("request", (request) => {
    if (/synthetic-filing\.invalid|\/submit(?:\?|$)/i.test(request.url())) {
      finalActionRequests.push(request.url());
    }
  });
  await page.route(`**/api/v1/portal-runs/${runId}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: runId,
        run_key: "SYNTHETIC-M7",
        portal_definition_id: portalId,
        portal_review_version_id: "review-1",
        portal_adapter_version_id: "adapter-1",
        compliance_case_id: "case-1",
        legal_entity_id: "entity-1",
        license_id: "license-1",
        form_instance_id: "form-1",
        document_packet_id: "packet-1",
        filing_type: "RENEWAL",
        automation_level: "PRE_SUBMISSION_ASSIST",
        status: "PRE_SUBMISSION_APPROVED",
        current_stage: "PRE_SUBMISSION_APPROVED",
        assigned_operator_id: "operator-1",
        assigned_signatory_id: "signatory-1",
        assigned_payment_approver_id: "approver-1",
        earliest_start_at: null,
        deadline_at: "2030-01-10T00:00:00Z",
        started_at: "2030-01-01T00:00:00Z",
        submitted_at: null,
        completed_at: null,
        last_error_code: null,
        last_error_message: null,
      }),
    }),
  );
  await page.route(`**/api/v1/portals/${portalId}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: portalId,
        name: "Synthetic portal",
        hostname: "synthetic-filing.invalid",
        status: "APPROVED_ASSISTED",
      }),
    }),
  );
  for (const suffix of ["handoffs", "fields", "documents", "timeline"]) {
    await page.route(`**/api/v1/portal-runs/${runId}/${suffix}`, (route) =>
      route.fulfill({ contentType: "application/json", body: "[]" }),
    );
  }
  await page.route(`**/api/v1/portal-runs/${runId}/browser-session`, (route) =>
    route.fulfill({ contentType: "application/json", body: "null" }),
  );
  await page.route(
    `**/api/v1/portal-runs/${runId}/request-final-submit-handoff`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: "handoff-final",
          portal_run_id: runId,
          handoff_type: "FINAL_SUBMIT",
          status: "REQUESTED",
        }),
      }),
  );

  await page.goto(`/portal-runs/${runId}`);
  await expect(
    page.getByRole("button", { name: "Request human final-submit handoff" }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Request human final-submit handoff" })
    .click();
  await expect(page).toHaveURL(/portal-handoffs\/handoff-final$/);
  expect(finalActionRequests).toEqual([]);
});
