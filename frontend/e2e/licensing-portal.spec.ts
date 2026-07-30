import { expect, test } from "@playwright/test";

test("Milestone 6 portal keeps NMLS as a channel and decisions advisory", async ({
  page,
}) => {
  await page.route("**/api/v1/licensing-dashboard/summary", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        advisory_notice:
          "Advisory operational result only; human review is required.",
        licenses_total: 1,
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
      }),
    }),
  );
  await page.route("**/api/v1/licensing-dashboard/blocked-cases", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/licenses?limit=250", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "00000000-0000-0000-0000-000000000061",
            license_key: "SYNTHETIC-CO-COLLECTION",
            license_number: "SYN-0001",
            current_status: "ACTIVE",
            filing_channel: "NMLS",
            expiration_date: "2030-12-31",
            renewal_due_date: "2030-11-30",
            responsible_owner: "synthetic-owner@example.invalid",
            source_confidence: "VERIFIED",
          },
        ],
      }),
    }),
  );

  await page.goto("/licensing");
  await expect(
    page.getByText(/Advisory operational result only/i),
  ).toBeVisible();
  await page.getByRole("link", { name: "Licenses", exact: true }).click();
  await expect(page.getByText("SYN-0001")).toBeVisible();
  await expect(page.getByText("NMLS", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/NMLS is shown as a filing channel/i),
  ).toBeVisible();
});
