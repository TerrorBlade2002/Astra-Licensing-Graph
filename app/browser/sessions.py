"""Process-local isolated Playwright contexts.

Database state coordinates ownership. Browser objects never enter PostgreSQL,
logs, or API responses.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app.browser.security import safe_profile_path
from app.core.config import Settings
from app.core.exceptions import StateConflictError


@dataclass
class LiveBrowserSession:
    session_id: uuid.UUID
    operator_user_id: uuid.UUID
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    profile_path: Path


class BrowserSessionRegistry:
    """One in-memory context per DB session, owned by one worker process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[uuid.UUID, LiveBrowserSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        session_id: uuid.UUID,
        operator_user_id: uuid.UUID,
        profile_id: str,
    ) -> LiveBrowserSession:
        async with self._lock:
            if session_id in self._sessions:
                raise StateConflictError("Browser session is already active in this worker.")
            profile_path = safe_profile_path(Path(self.settings.browser_temp_root), profile_id)
            profile_path.mkdir(parents=True, exist_ok=False)
            engine = await async_playwright().start()
            browser_type = getattr(engine, self.settings.browser_type)
            browser = await browser_type.launch(
                headless=self.settings.browser_headless,
                args=["--disable-extensions", "--disable-sync", "--no-default-browser-check"],
                timeout=self.settings.browser_navigation_timeout_seconds * 1000,
            )
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
            )
            context.set_default_timeout(self.settings.browser_action_timeout_seconds * 1000)
            context.set_default_navigation_timeout(
                self.settings.browser_navigation_timeout_seconds * 1000
            )
            live = LiveBrowserSession(
                session_id=session_id,
                operator_user_id=operator_user_id,
                playwright=engine,
                browser=browser,
                context=context,
                profile_path=profile_path,
            )
            self._sessions[session_id] = live
            return live

    def get(self, session_id: uuid.UUID, *, operator_user_id: uuid.UUID) -> LiveBrowserSession:
        live = self._sessions.get(session_id)
        if live is None:
            raise StateConflictError("Browser session is not active in this worker.")
        if live.operator_user_id != operator_user_id:
            raise StateConflictError("A browser session cannot be reused by another operator.")
        return live

    async def close(self, session_id: uuid.UUID) -> None:
        async with self._lock:
            live = self._sessions.pop(session_id, None)
        if live is None:
            return
        try:
            await live.context.close()
            await live.browser.close()
            await live.playwright.stop()
        finally:
            root = Path(self.settings.browser_temp_root).resolve()
            target = live.profile_path.resolve()
            if root in target.parents and target.exists():
                shutil.rmtree(target)
