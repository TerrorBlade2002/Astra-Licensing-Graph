# Ambiguous-send recovery

Email send is not safely repeatable. A timeout, read/write failure, HTTP 408, or gateway/server 5xx during or after the Graph send POST becomes `SEND_AMBIGUOUS`. The attempt and immutable draft ID are retained, a high-priority reconciliation job is created, and no second send POST is permitted. Only failures proven to occur before transmission (token acquisition/connection establishment) and an explicit 429 response use the bounded safe-retry path.

Reconciliation retrieves the immutable message ID. If it is a non-draft message in the shared mailbox Sent Items folder with `sentDateTime`, the attempt becomes `SENT_COPY_VERIFIED`. If it is still a draft, or remains missing beyond the bounded observation window, the case stays ambiguous and requires Manager review.

Operators use `python -m app.cli.send_reconcile --draft-id <uuid>`. Review attempt history and Graph request IDs, never body or recipient logs. A manual resend requires a documented recovery decision and a new controlled approval flow; never retry the old ambiguous attempt.
