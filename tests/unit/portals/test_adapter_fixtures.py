from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.portals.adapters.nmls import NMLSAssistedAdapter

FIXTURES = Path(__file__).parents[2] / "fixtures" / "portals"
KNOWN_CATEGORIES = (
    "login",
    "dashboard",
    "field",
    "upload",
    "validation",
    "attestation",
    "payment",
    "final_submit",
    "confirmation",
)


def _contract() -> dict[str, object]:
    return {
        category: {
            "fingerprint": {
                "strategy": "test_id",
                "value": f"page-{category.replace('_', '-')}",
            },
            "page_fingerprint": f"synthetic-{category}-v1",
            "locators": {},
        }
        for category in KNOWN_CATEGORIES
    }


@pytest.mark.asyncio
async def test_nmls_adapter_identifies_only_reviewed_local_pages() -> None:
    adapter = NMLSAssistedAdapter(locator_contract=_contract(), contract_version="1")
    engine = await async_playwright().start()
    browser = await engine.chromium.launch(headless=True)
    try:
        page = await browser.new_page()
        for category in KNOWN_CATEGORIES:
            fixture = FIXTURES / f"{category}.html"
            await page.goto(fixture.as_uri(), wait_until="domcontentloaded")
            identity = await adapter.identify_current_page(page)
            assert identity is not None
            assert identity.category == category
        await page.goto((FIXTURES / "unknown.html").as_uri(), wait_until="domcontentloaded")
        assert await adapter.identify_current_page(page) is None
        diagnostic = await adapter.collect_page_contract(page)
        assert diagnostic["category"] == "UNKNOWN"
        assert "html" not in diagnostic
    finally:
        await browser.close()
        await engine.stop()


def test_nmls_adapter_exposes_no_final_action() -> None:
    adapter = NMLSAssistedAdapter(locator_contract=_contract(), contract_version="1")
    for method_name in (
        "accept_terms",
        "enter_mfa",
        "solve_captcha",
        "attest",
        "sign",
        "pay",
        "submit",
    ):
        assert not hasattr(adapter, method_name)
