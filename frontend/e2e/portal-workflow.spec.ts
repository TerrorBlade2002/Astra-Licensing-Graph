import { expect, test } from "@playwright/test";

test("reviewer corrects evidence and creates an assigned task", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Good morning/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Review queue", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Classification review" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Review →" }).click();
  await expect(page.getByText("Source evidence")).toBeVisible();

  const item = page.locator('input[name="requested_information.0.item"]');
  await item.fill("Verified current toll-free telephone number");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(page.getByText("CORRECTED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Create licensing task →" }).click();
  await expect(
    page.getByRole("heading", { name: /Colorado - Collection Agency License/ }),
  ).toBeVisible();
  await page.getByLabel("Owner").fill("owner@astra.example");
  await page.getByRole("button", { name: "Assign", exact: true }).click();
  await expect(page.getByText("owner@astra.example")).toBeVisible();
  await page.getByRole("button", { name: "IN REVIEW" }).click();
  await expect(page.getByText("IN REVIEW", { exact: true })).toBeVisible();
  await page
    .getByRole("button", {
      name: "Mark Verified current toll-free telephone number verified",
    })
    .click();
  await expect(page.getByText("VERIFIED", { exact: true })).toBeVisible();
  await expect(page.getByText("REQUESTED ITEM UPDATED")).toBeVisible();
  await expect(
    page.getByText("no send action", { exact: false }),
  ).toBeVisible();
});
