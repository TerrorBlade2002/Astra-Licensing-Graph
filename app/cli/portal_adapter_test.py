"""Exercise a reviewed adapter against a synthetic local HTML fixture only."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import select

from app.cli.licensing_common import session_scope
from app.core.exceptions import StateConflictError
from app.models import PortalAdapterVersion, PortalDefinition
from app.portals.enums import AdapterStatus
from app.portals.registry import build_adapter


async def _run(portal_key: str, fixture_name: str) -> dict[str, object]:
    fixture_root = (Path(__file__).parents[2] / "tests" / "fixtures" / "portals").resolve()
    fixture = (fixture_root / fixture_name).resolve()
    if fixture_root not in fixture.parents or not fixture.is_file() or fixture.suffix != ".html":
        raise StateConflictError("Fixture must be an HTML file under tests/fixtures/portals.")
    async with session_scope() as session:
        portal = await session.scalar(
            select(PortalDefinition).where(PortalDefinition.portal_key == portal_key)
        )
        if portal is None:
            raise StateConflictError("Portal not found.")
        version = await session.scalar(
            select(PortalAdapterVersion).where(
                PortalAdapterVersion.portal_definition_id == portal.id,
                PortalAdapterVersion.status == AdapterStatus.ACTIVE.value,
            )
        )
        if version is None:
            raise StateConflictError("Portal has no active adapter.")
        adapter = build_adapter(
            version.adapter_key,
            locator_contract=version.locator_contract,
            contract_version=str(version.version),
        )
    engine = await async_playwright().start()
    browser = await engine.chromium.launch(headless=True)
    try:
        context = await browser.new_context(service_workers="block")
        page = await context.new_page()
        await page.goto(fixture.as_uri(), wait_until="domcontentloaded")
        identity = await adapter.identify_current_page(page)
        return {
            "portal_key": portal_key,
            "fixture": fixture.name,
            "identified": identity is not None,
            "page_category": identity.category if identity else "UNKNOWN",
            "adapter_version": version.version,
            "network_target": "local-fixture-only",
        }
    finally:
        await browser.close()
        await engine.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal-key", required=True)
    parser.add_argument("--fixture", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_run(args.portal_key, args.fixture)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
