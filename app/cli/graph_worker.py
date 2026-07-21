"""Alias entry point: `python -m app.cli.graph_worker` == `python -m app.workers.runner`."""

from __future__ import annotations

import sys

from app.workers.runner import main

if __name__ == "__main__":
    sys.exit(main())
