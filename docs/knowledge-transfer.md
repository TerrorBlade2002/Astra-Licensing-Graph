# Astra Licensing Automation — Knowledge Transfer Blueprint

**Purpose.** Replace manual handling of the licensing mailbox
(`astralicensing@astraglobal.com`) with an automated assembly line: an email
arrives → the system captures it → understands it → a person approves → a
task/reply is created → the message is filed and tracked → (later) regulator
forms are auto-filled. This document is the handover: what's done, what's left,
and *why* each choice was made.

---

## 1. The pipeline at a glance

Each email moves through fixed stages. Status is honest as of now:

| # | Stage | Plain meaning | Status |
|---|---|---|---|
| 1 | **Foundation** | Secure database + audit trail everything runs on | Done & tested |
| 2 | **Email intake** | Auto-capture every email + attachments, saved & hashed | Done & tested |
| 3 | **Classify** | System reads each email, proposes type/state/action | Built, wired into pipeline (verification finishing) |
| 4 | **Human review** | Staff approve/correct on a review screen | In progress (portal being built) |
| 5 | **Document library** | Upload supporting files once, reuse automatically | SharePoint-first (not started) |
| 6 | **Act & file** | Draft reply → send → move email to right folder | Not started (interfaces reserved) |
| 7 | **Form-filling** | Auto-fill NMLS/Sircon forms | Future (needs stakeholder alignment) |

**Golden rule:** nothing goes *out* (send, file to regulator, submit form)
without a human approving first. This is a compliance guardrail, not a
limitation.

---

## 2. What's built — and why

**Stage 1 — Foundation (done)**
- PostgreSQL database, versioned migrations, a strict state machine (an email
  can only move DISCOVERED → FETCHED → … in valid steps), full audit log, and
  a read-only API to inspect everything.
- *Why:* the old prototype stored data in loose JSON files — not safe for
  production. A real database gives durability, a tamper-evident audit trail,
  and safe concurrent processing.

**Stage 2 — Email intake (done, tested end-to-end on mock data)**
- The system subscribes to the mailbox, gets notified of new mail, then pulls
  the **authoritative** list of changes and saves each email, its raw copy,
  and attachments — every file fingerprinted (SHA-256) so nothing is lost or
  duplicated.
- *Why notifications aren't trusted directly:* Microsoft notifications can
  duplicate or drop. We treat a notification only as "something changed — go
  check," then read the exact change list. This is what makes it reliable.
- *Why the checkpoint only advances after a full successful pass:* if a crash
  happens mid-way, we replay safely and never miss or double-count an email.
- *Why security is strict:* the mailbox secret is stored only as a one-way
  hash and checked in constant time; access tokens and email bodies never
  appear in logs. This protects client data by design.

**Stage 3 — Classify (built, finishing verification)**
- Deterministic rules (ported from the proven prototype) plus an AI model
  propose: vendor, state, license type, what's being asked, and the due date —
  with a confidence score.
- *Why rules + AI together:* rules are predictable and auditable; AI handles
  the messy free-text. Every classification is versioned, so corrections keep
  history.

---

## 3. What's left — action-based

| Stage | Action to take | Needs admin access? | Owner |
|---|---|---|---|
| **Go-live (Stage 2)** | Point the system at the real mailbox over a public HTTPS address; confirm mailbox permissions | Yes — Exchange/webhook | → Arsh |
| **Review portal (Stage 4)** | Finish the approval screen; add real login (Entra sign-in) | Yes — Entra app + consent | → Arsh (with Arnab) |
| **Document library (Stage 5)** | Set up **SharePoint site first** (folders by state/vendor/license, permissions), then connect it so files upload once and are fetched automatically | Yes — SharePoint site | Set up by Arsh, connected by engineering |
| **Act & file (Stage 6)** | Turn on draft reply, send, and move-to-folder | Yes — sign-off to send/move | → Arsh |
| **Form-filling (Stage 7)** | Scope & build NMLS/Sircon auto-fill | Yes — portal logins | → Arsh after alignment |

**Why the document library is SharePoint-first:** staff already know
SharePoint, so there's zero new tool to learn and minimal training. It becomes
the single home for reusable documents (bonds, licenses, forms) *and* the data
source that later feeds form-filling. Starting here is the simplest,
lowest-risk path.

---

## 4. How to run it (operational quick-reference)

- **Database:** PostgreSQL via Docker on **host port 5442** (this machine
  already uses 5432/5433/5434/5439).
- **Start:** `docker compose up -d db` → `alembic upgrade head` →
  `uvicorn app.main:app` →
  `python -m app.workers.runner --queues subscriptions,sync,ingestion`.
- **Health/visibility:** `/health/ready`,
  `/api/v1/integrations/graph/status`, `/metrics`.
- **Everything runs on test data today.** No live Microsoft/OpenAI call
  happens in tests — all mocked, and CI blocks those hostnames. Going live is
  a deliberate admin step, not a code change.
- **Full details:** see `docs/` (graph-integration, webhook-security,
  delta-synchronization, graph-operations-runbook, staging-acceptance).

---

## 5. Non-negotiable guardrails (the "whys" that must survive)

1. **Human approves before any outward action** — no auto-send, no auto-move,
   no auto-submit to a regulator. Compliance requirement.
2. **Delta sync is the source of truth**, not notifications — reliability.
3. **Checkpoint advances only after a complete pass** — crash-safety.
4. **Secrets/tokens/email bodies never logged; mailbox secret stored hashed** —
   data protection.
5. **Filesystem storage is dev-only and blocked in production** — real
   evidence must live in SharePoint (Stage 5).

---

## 6. Immediate next actions

- [ ] **Arsh:** stand up the **SharePoint document library** (site + folders +
  permissions) — this unblocks Stage 5 and production config.
- [ ] **Arsh:** go-live of email intake on the real mailbox (public HTTPS +
  Exchange sign-off).
- [ ] **Arnab → handover:** finish classification verification; document the
  review-portal remaining work.
- [ ] **Arsh:** register the review portal in Entra (login) and get sign-off to
  enable send/move.
- [ ] **Arsh:** align **Sanjiv, Vikas, Amit Takiar, Saurabh** on form-filling
  scope, data source (the SharePoint library), portal logins, and mandatory
  human approval before any filing.
