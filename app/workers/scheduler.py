"""Scheduler entry point.

``app.workers.scheduling`` holds the implementation; this module is the name
used by the deployed cron service:

    python -m app.workers.scheduler --once

One cycle enqueues durable jobs (subscription maintenance, Inbox
reconciliation, deadline materialization, document-expiry and
stale-information checks), recovers abandoned leases, expires portal reviews,
authorizations, and browser sessions, and exits. It never performs business
processing itself.
"""

from __future__ import annotations

import sys

from app.workers.scheduling import main, run_scheduler_cycle, run_scheduler_loop

__all__ = ["main", "run_scheduler_cycle", "run_scheduler_loop"]


if __name__ == "__main__":
    sys.exit(main())
