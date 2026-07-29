# Milestone 5 staging acceptance

Use only a synthetic internal recipient and synthetic approved documents. Record tester, approver, timestamps, safe internal IDs, and outcome. Never place credentials or upload URLs in evidence.

1. Verify Mail.ReadWrite/Mail.Send and mailbox-scoped Exchange RBAC; prove an unrelated mailbox is denied.
2. Create a reply draft. Confirm the shared Drafts copy, Graph-generated recipient, immutable ID, and `isDraft=true`; confirm nothing was sent.
   Also inject an ambiguous `createReply`, confirm there is no second create call, and verify reconciliation accepts only one source-conversation candidate.
3. Edit the draft in Outlook. Reconcile and confirm a new revision plus approval invalidation.
4. Attach an approved synthetic small PDF; verify filename, size, hash, and invalidation.
5. With separate authorization only, enable the large-attachment flags, exercise the shared-mailbox upload-session path, verify sequential ranges/final attachment, and prove no upload URL was logged. Disable the flag after the test.
6. Have a Reviewer submit and a different Sender approve the exact snapshot. Modify it, confirm invalidation, and approve the corrected snapshot.
7. Enable send for one synthetic internal recipient. Confirm Astra queues first, Graph later returns `202 SEND_ACCEPTED`, the UI does not say Delivered, Sent Items becomes verified by immutable ID, and delivery remains `UNKNOWN`.
8. Inject a post-request timeout. Confirm `SEND_AMBIGUOUS`, no second POST, and successful reconciliation.
9. Move the verified source, confirm returned parent folder, then finalize. Confirm email `MOVED -> COMPLETED` and licensing task remains open or waiting.
10. Exercise `NO_RESPONSE_REQUIRED`: no draft/send, verified routing, workflow completion.

Production flags remain disabled until all applicable gates have signed evidence.
