# Microsoft Graph integration (Milestone 2)

## Scope

Milestone 2 implements the production Graph ingestion boundary: app-only
authentication, Outlook message subscriptions, webhook receivers, a durable
PostgreSQL job queue, Inbox delta synchronization, and email evidence capture
(full JSON + raw MIME + attachments) through `ATTACHMENTS_SAVED`.

It deliberately does **not** classify, create tasks, draft, send, or move
messages, and it never requests organization-wide mailbox access — Exchange
RBAC already scopes the app to the licensing shared mailbox.

## App-only authentication

`MsalConfidentialClientTokenProvider` ([app/graph/auth.py](../app/graph/auth.py))
acquires app-only tokens via MSAL's confidential-client flow using the
`.default` Graph scope. Client-secret and certificate credentials are both
supported through configuration (`GRAPH_CREDENTIAL_MODE`); the interface stays
open for managed identity later.

- Tokens are cached in-process with a refresh skew
  (`GRAPH_TOKEN_REFRESH_SKEW_SECONDS`) and an asyncio lock so concurrent
  callers cause one acquisition.
- Tokens are never persisted to PostgreSQL, never logged, and never included
  in exception messages. Auth failures surface sanitized error codes only.
- On a Graph 401 the client force-refreshes and retries exactly once; a second
  401 becomes a non-retryable `GraphAuthError`.

## Graph HTTP client

`GraphHttpClient` ([app/graph/client.py](../app/graph/client.py)) is raw async
HTTPX with explicit policy:

- Default headers: `Accept: application/json`, `Prefer: IdType="ImmutableId"`
  (immutable IDs survive folder moves), generated `client-request-id`,
  `return-client-request-id: true`. Extra `Prefer` values are merged, never
  clobbered.
- Retryable: network failures/timeouts, 408, 429, 500, 502, 503, 504.
  429 honours `Retry-After`; otherwise bounded exponential backoff with full
  jitter (`app/graph/retry.py`). 400/403/404 and schema failures never retry.
- Errors are translated to `GraphApiError` carrying only sanitized fields
  (status, Graph error code, request IDs, retry-after) — never the
  Authorization header, token, or response bodies containing mail content.
- Binary bodies (MIME, attachments) stream directly into the evidence store
  with SHA-256 computed on the fly; nothing is buffered wholesale in memory.

## Continuation-URL security

Saved `nextLink`/`deltaLink` values are validated before every call
([app/graph/urls.py](../app/graph/urls.py)): HTTPS only, the configured Graph
host only, no embedded credentials, no fragments, no unexpected ports, v1.0
path required. Logs carry only a SHA-256 fingerprint, hostname, and a coarse
path category — never the URL itself.

## Subscriptions

See [webhook-security.md](webhook-security.md) for clientState handling and
the notification trust model. Lifecycle summary:

```
ensure_subscription(mailbox, folder)
  ├─ no row / REMOVED / EXPIRED ────────► create (CREATING → ACTIVE)
  ├─ ACTIVE, expiry far away ───────────► no-op
  ├─ ACTIVE in renewal window ──────────► PATCH renew
  ├─ RENEWAL_REQUIRED / REAUTH_REQUIRED ► renew (404 → recreate)
  └─ multiple active rows ──────────────► SubscriptionConflictError (human)
```

Creation order matters: the local row (with the clientState **hash**) is
committed *before* the Graph call, because Graph validates the webhook — and
can even deliver a first notification — before the create call returns. A
notification arriving for a still-CREATING row is matched by clientState hash
plus resource and bound to the returned subscription ID when unambiguous.

## Job flow

```
webhook ──► graph_notification_receipts ──► graph_jobs (SYNC_FOLDER, coalesced)
                                              │  claim: FOR UPDATE SKIP LOCKED
worker ◄──────────────────────────────────────┘  lease + heartbeat + retry
  │ delta sync ──► emails upserted (DISCOVERED) ──► graph_jobs (INGEST_EMAIL)
  │ ingestion ──► message.json + message.eml + attachments ──► ATTACHMENTS_SAVED
scheduler ──► ensure/renew subscriptions, periodic reconciliation sync,
              expired-lease recovery (single replica via advisory lock)
```

Details: [delta-synchronization.md](delta-synchronization.md) and
[graph-operations-runbook.md](graph-operations-runbook.md).

## Ingestion flow

1. Full message (`$select`, `Prefer: outlook.body-content-type="text"`) →
   canonical JSON → evidence store → `full_message_json_*` columns.
2. Raw MIME (`/$value`) streamed with `MAX_RAW_MIME_BYTES` enforced →
   `raw_mime_*` columns.
3. Only after both artifacts persist: `DISCOVERED → FETCHED` through the
   Milestone 1 atomic transition service (evidence URIs/hashes in event
   metadata, never body content).
4. Attachments listed and downloaded by type: `fileAttachment` streamed via
   `/$value`; `itemAttachment` stored as its Graph JSON representation;
   `referenceAttachment` recorded as `REFERENCE_NOT_DOWNLOADED`. Limits
   (count, bytes, MIME allowlist) quarantine rather than buffer.
5. `FETCHED → ATTACHMENTS_SAVED` only when every attachment is terminal
   (DOWNLOADED / REFERENCE_NOT_DOWNLOADED / QUARANTINED).

## Security boundaries

- The webhook handler never calls Graph and returns 202 after durable writes.
- Mutating operational endpoints are refused when `APP_ENV=production` until
  the Entra actor layer (Milestone 4) exists.
- The filesystem evidence backend is rejected at production startup.
- Secrets, tokens, clientState, delta links, mail bodies, and attachment
  bytes are excluded from logs, metrics labels, and API responses.
