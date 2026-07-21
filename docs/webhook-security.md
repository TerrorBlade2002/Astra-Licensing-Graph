# Webhook security

## Endpoints

- `POST /webhooks/microsoft-graph/messages` — change notifications
- `POST /webhooks/microsoft-graph/lifecycle` — lifecycle notifications

Both live outside `/api/v1` and outside the CurrentActor dependency: Graph
authenticates itself through clientState, not through our user auth.

## validationToken handling

When `?validationToken=` is present the handler returns HTTP 200 with
`Content-Type: text/plain` and the exact URL-decoded token as the body —
decoded once (by the framework), length-capped, treated as opaque, never
logged, never persisted, and never processed as a notification.

## clientState

- Generated per subscription: 32 cryptographically secure random bytes,
  URL-safe Base64 without padding (`secrets.token_bytes`).
- The plaintext is sent to Graph exactly once, inside the subscription
  creation request, and is deliberately dropped afterwards.
- Only the SHA-256 hash is stored (`graph_subscriptions.client_state_hash`).
- Every received notification's clientState is hashed and compared with
  `hmac.compare_digest` (constant-time). Microsoft documents clientState as
  the mechanism for confirming a notification belongs to your subscription —
  nothing in a notification is trusted before this check passes.
- Invalid clientState: an `INVALID_CLIENT_STATE` receipt is persisted, a
  security warning is logged, a metric increments, **no job is created**, and
  the response is still 202 so an attacker learns nothing about whether the
  subscription exists.

## Tenant validation

When `GRAPH_EXPECTED_TENANT_ID` is configured, notifications carrying a
different `tenantId` are recorded as MALFORMED and ignored.

## Body limits and malformed input

- Bodies over `GRAPH_WEBHOOK_MAX_BODY_BYTES` (default 256 KiB) → 413; the
  body is read incrementally, never unbounded into memory.
- Structurally invalid JSON or a missing `value[]` → 400, nothing enqueued.
- Individually malformed items inside a valid collection are receipted as
  MALFORMED where a subscription ID exists; valid siblings still process; the
  collection returns 202.

## Duplicate handling

Each notification gets a deterministic idempotency key:
`sha256(subscriptionId | notification.id | lifecycleEvent | changeType)` when
Graph supplies `id`, otherwise a canonical hash of subscriptionId, tenantId,
resource, changeType, lifecycleEvent, and expiration. Plaintext clientState is
never part of the key. A replayed notification hits the receipts unique
constraint, is marked DUPLICATE, and creates no job.

## Why webhook payloads are not authoritative

A notification only means "something may have changed". The handler persists
a receipt and enqueues a coalesced `SYNC_FOLDER` job; the saved folder
deltaLink is the single source of truth for what actually changed. Resource
data is never requested in notifications, so no mail content ever transits
the webhook.

## Network and TLS considerations

- Subscriptions are created with `latestSupportedTlsVersion=v1_2`.
- `PUBLIC_BASE_URL` must be HTTPS outside local/test and must not be
  localhost; production startup enforces this.
- Optional hardening (infrastructure-level, not in this codebase): allowlist
  Microsoft 365 egress ranges in front of the webhook path, and terminate TLS
  at a proxy that preserves the original body untouched (the size limit is
  enforced again in-app).
