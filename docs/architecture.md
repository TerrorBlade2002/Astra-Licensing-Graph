# Architecture — Milestone 1

## Purpose

Milestone 1 replaces the PowerShell prototype's JSON-file persistence with a
production PostgreSQL data model behind a FastAPI service. No live Microsoft
Graph, SharePoint, or LLM call is made in this milestone.

## Components

```
                    ┌─────────────────────────────────────────────┐
                    │                 FastAPI app                  │
                    │  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
   HTTP ───────────▶│  │ /health  │  │ /api/v1  │  │  /docs    │  │
                    │  └──────────┘  └────┬─────┘  └───────────┘  │
                    │       middleware: correlation-ID, CORS       │
                    │       exception handlers: error envelope     │
                    ├──────────────────────┼───────────────────────┤
                    │      services        │      (read side)      │
                    │  email_state (atomic │  task_queries         │
                    │  transitions + audit │                       │
                    │  + outbox)           │                       │
                    ├──────────────────────┼───────────────────────┤
                    │            repositories (data access)        │
                    ├──────────────────────┼───────────────────────┤
                    │        SQLAlchemy 2 async + asyncpg          │
                    └──────────────────────┬───────────────────────┘
                                           │
                                    ┌──────▼──────┐
                                    │ PostgreSQL  │  (Alembic-managed schema)
                                    └─────────────┘

   CLI (same service/repository layers):
     app.cli.import_prototype   ← reads prototype-data/ JSON files
     app.cli.seed_dev           ← synthetic development data
```

## Layering rules

- Routers hold no SQL and no business rules; they parse/validate input and
  call services.
- Services own transactions, transition validation, idempotency, and audit +
  outbox row creation.
- Repositories are thin query/write helpers over one `AsyncSession`.
- One `AsyncSession` per request (FastAPI dependency) or per unit of work
  (CLI); sessions are never shared across concurrent tasks.

## Request flow

1. Request enters `CorrelationIdMiddleware`: `X-Correlation-ID` is accepted
   only when it is a valid UUID, otherwise a new UUID is generated. The value
   is stored in a `ContextVar`, echoed on the response, and attached to every
   log line and audit/event row written during the request.
2. The router resolves dependencies (settings, session, actor) and calls a
   service function.
3. Domain errors map to the standard error envelope with an HTTP status from
   the exception class; unexpected errors return a redacted 500 envelope.

## Future integration boundaries (not implemented here)

- **Graph worker** — a separate worker process will consume
  `mailbox_sync_state` (delta links, folder leases) and write emails through
  the same state-transition service. Webhook ingestion lands in the API as a
  thin endpoint that enqueues work; no Graph call happens in the request path.
- **Queue publication** — `outbox_events` rows are written transactionally
  with state transitions. A future publisher drains PENDING rows to Azure
  Service Bus; `idempotency_key` guarantees exactly-once handoff.
- **SharePoint document storage** — `storage_uri` fields are URI-typed
  (`file://` today) precisely so a `https://sharepoint...` or `spo://` scheme
  can replace local paths without schema change.
- **Review portal** — the read-only API is the contract for the future
  React/Next.js portal. Microsoft Entra JWT validation replaces the
  development actor before any portal exposure (`AUTH_MODE=entra`).
- **PowerShell acceptance tooling** — the prototype scripts in
  `scripts/powershell-acceptance-tests/` remain the recovery/acceptance tools
  for the mailbox side; they no longer define the data architecture.
