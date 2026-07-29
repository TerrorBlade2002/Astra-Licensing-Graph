import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommunicationStatusPage } from "../pages/CommunicationStatusPage";
import { SendApprovalQueuePage } from "../pages/SendApprovalQueuePage";

const draft = {
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
  draft_status: "SEND_ACCEPTED",
  local_revision: 2,
  graph_draft_message_id: "immutable-id",
  graph_change_key: "ck",
  graph_etag: "etag",
  approval_snapshot_sha256: "abc",
  pending_approval_snapshot_sha256: "abc",
  last_edited_by_actor: "reviewer",
  delivery_status: "UNKNOWN",
  attachments: [],
};

function wrapper(children: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

it("does not present Graph acceptance as delivery", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify(
          url.includes("dashboard")
            ? {
                pending_send_approval: 0,
                send_ambiguous: 0,
                workflows_completed: 0,
              }
            : [draft],
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  render(wrapper(<CommunicationStatusPage />));
  expect(
    await screen.findByText(/Delivery is not confirmed/i),
  ).toBeInTheDocument();
  expect(screen.queryByText(/^Delivered$/i)).not.toBeInTheDocument();
});

it("requires an explicit confirmation before queueing an approved send", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify([{ ...draft, draft_status: "APPROVED_TO_SEND" }]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  render(wrapper(<SendApprovalQueuePage />));
  const queue = await screen.findByRole("button", {
    name: /Queue approved send/i,
  });
  expect(queue).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  expect(queue).toBeEnabled();
});
