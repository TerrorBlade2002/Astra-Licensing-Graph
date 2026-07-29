# Graph draft and send administration

Before enabling staging flags, verify:

1. The Entra application has application `Mail.ReadWrite` and `Mail.Send`.
2. Exchange RBAC for Applications scopes both permissions to the configured licensing shared mailbox.
3. The same application is denied against an unrelated test mailbox.
4. Shared mailbox Drafts and Sent Items folders are discovered and stored.
5. Exchange shared-mailbox copies are retained with `MessageCopyForSentAsEnabled` and `MessageCopyForSendOnBehalfEnabled` according to organizational policy.
6. Requests include `Prefer: IdType="ImmutableId"`.
7. The backend token never appears in frontend code, browser storage, logs, or assets.
8. `Licensing.Sender` assignments and separation-of-duties policy are reviewed.
9. Graph mutation flags remain false until their staging gates pass.

Draft creation uses `createReply` or explicitly reviewed `createReplyAll`, never one-step reply/send. Sending uses `POST /messages/{immutable-draft-id}/send` only after exact approval. Graph `202` is recorded as `SEND_ACCEPTED`, never Delivered. Sent Items verification is a later state and delivery defaults to `UNKNOWN`.

Run `python -m app.cli.communication_diagnostics permissions --mailbox <shared-mailbox>` for a non-sending runtime read probe. Verify Mail.Send and Exchange scope administratively; the CLI intentionally sends nothing.
