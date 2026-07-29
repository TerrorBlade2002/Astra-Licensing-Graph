import { expect, test } from "@playwright/test";

test("different Sender approves an exact snapshot and explicitly queues send", async ({
  page,
}) => {
  let status = "PENDING_SEND_APPROVAL";
  let queued = false;
  const draft = () => ({
    id: "draft-1",
    response_plan_id: "plan-1",
    task_id: "task-1",
    email_id: "email-1",
    subject: "Synthetic acknowledgement",
    body_text: "We acknowledge receipt.",
    body_html: null,
    to_recipients: [{ address: "synthetic@example.invalid", name: "" }],
    cc_recipients: [],
    bcc_recipients: [],
    draft_status: status,
    local_revision: 2,
    graph_draft_message_id: "immutable-id",
    graph_change_key: "ck",
    graph_etag: "etag",
    approval_snapshot_sha256: status === "APPROVED_TO_SEND" ? "hash" : null,
    pending_approval_snapshot_sha256: "hash",
    last_edited_by_actor: "reviewer-dev",
    delivery_status: "NOT_APPLICABLE",
    attachments: [],
  });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        user_id: "sender-dev",
        display_name: "Sender",
        principal_name: "sender@example.invalid",
        roles: ["Licensing.Sender"],
        capabilities: ["approve_send", "queue_send"],
      },
    }),
  );
  await page.route("**/api/v1/outbound-drafts", (route) =>
    route.fulfill({ json: [draft()] }),
  );
  await page.route(
    "**/api/v1/outbound-drafts/draft-1/approve-send",
    async (route) => {
      status = "APPROVED_TO_SEND";
      await route.fulfill({
        json: {
          id: "approval-1",
          decision: "APPROVED",
          snapshot_sha256: "hash",
        },
      });
    },
  );
  await page.route("**/api/v1/outbound-drafts/draft-1/send", async (route) => {
    const body = route.request().postDataJSON();
    queued = body.explicit_confirmation === true;
    await route.fulfill({
      status: 202,
      json: { job_id: "job-1", status: "SEND_QUEUED" },
    });
  });
  await page.goto("/communications/approvals");
  await expect(
    page.getByRole("heading", { name: "Send approval" }),
  ).toBeVisible();
  await expect(page.getByText("synthetic@example.invalid")).toBeVisible();
  await page.getByRole("button", { name: "Approve exact snapshot" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Queue approved send" }).click();
  expect(queued).toBe(true);
});
