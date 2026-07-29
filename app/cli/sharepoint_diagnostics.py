"""Secret-free SharePoint Sites.Selected readiness diagnostics."""

from __future__ import annotations

import asyncio
import json
import sys

from app.core.config import get_settings
from app.graph.auth import MsalConfidentialClientTokenProvider
from app.graph.client import GraphHttpClient
from app.services.sharepoint_readiness import SharePointReadinessService
from app.sharepoint.client import SharePointClient


async def run() -> int:
    settings = get_settings()
    graph = GraphHttpClient(settings, MsalConfidentialClientTokenProvider(settings))
    client = SharePointClient(graph, settings)
    try:
        report = await SharePointReadinessService(client, settings).check()
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ready else 1
    finally:
        await client.aclose()
        await graph.aclose()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
