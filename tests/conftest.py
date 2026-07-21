"""Shared test fixtures.

Integration and API tests run against a real PostgreSQL database
(``TEST_DATABASE_URL``, default: the compose-provisioned astra_licensing_test).
The schema is created once per session via Alembic; tables are truncated
before each test for determinism.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.main import create_app
from app.models import Base, Email, Mailbox

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing_test"
)


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


async def _ensure_database_exists(url: str) -> None:
    # Connect to the maintenance database on the same server and create the
    # test database when the compose init script has not provisioned it.
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    base, _, dbname = dsn.rpartition("/")
    admin = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _test_database_url()


@pytest.fixture(scope="session")
def alembic_config(test_database_url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_database_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_database(test_database_url: str, alembic_config: Config) -> Iterator[None]:
    asyncio.run(_ensure_database_exists(test_database_url))
    os.environ["DATABASE_URL"] = test_database_url
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    # NullPool: one engine per test function, no cross-event-loop reuse.
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


def make_test_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": database_url,
        "LOG_FORMAT": "console",
        "AUTH_MODE": "development",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def app(test_database_url: str, session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    return create_app(make_test_settings(test_database_url))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


# -------------------------------------------------------------- graph helpers


class FakeTokenProvider:
    """Deterministic token provider for mocked Graph tests."""

    def __init__(self, token: str = "synthetic-test-token") -> None:
        self.token = token
        self.calls = 0
        self.force_refreshes = 0

    async def get_access_token(self, force_refresh: bool = False) -> str:
        self.calls += 1
        if force_refresh:
            self.force_refreshes += 1
        return self.token


@pytest.fixture
def graph_settings(test_database_url: str, tmp_path: Path) -> Settings:
    return make_test_settings(
        test_database_url,
        GRAPH_ENABLED=True,
        GRAPH_TENANT_ID="00000000-0000-0000-0000-00000000t3st",
        GRAPH_CLIENT_ID="synthetic-client-id",
        GRAPH_CLIENT_SECRET="synthetic-client-secret",
        FILESYSTEM_EVIDENCE_ROOT=str(tmp_path / "evidence"),
        GRAPH_MAX_RETRY_ATTEMPTS=3,
        GRAPH_MAX_RETRY_DELAY_SECONDS=0.05,
        GRAPH_JOB_RETRY_BASE_SECONDS=0.01,
        GRAPH_JOB_RETRY_MAX_SECONDS=0.05,
        GRAPH_WORKER_POLL_INTERVAL_SECONDS=0.01,
    )


@pytest.fixture
def fake_token_provider() -> FakeTokenProvider:
    return FakeTokenProvider()


@pytest.fixture
async def graph_client(graph_settings: Settings, fake_token_provider: FakeTokenProvider):
    from app.graph.client import GraphHttpClient

    client = GraphHttpClient(graph_settings, fake_token_provider)
    yield client
    await client.aclose()


@pytest.fixture
def evidence_store(graph_settings: Settings):
    from app.evidence.filesystem import FilesystemEvidenceStore

    return FilesystemEvidenceStore(graph_settings.filesystem_evidence_root)


async def create_inbox_folder(session: AsyncSession, mailbox: Mailbox):
    from app.models import MailboxFolder

    folder = MailboxFolder(
        id=uuid.uuid4(),
        mailbox_id=mailbox.id,
        graph_folder_id="SYNTH-FOLDER-INBOX",
        display_name="Inbox",
        folder_path="Inbox",
    )
    session.add(folder)
    await session.flush()
    return folder


async def create_subscription_row(
    session: AsyncSession,
    mailbox: Mailbox,
    folder: Any,
    *,
    client_state: str = "synthetic-client-state",
    graph_subscription_id: str | None = "synth-sub-001",
    status: str = "ACTIVE",
):
    from app.models import GraphSubscription
    from app.webhooks.security import hash_client_state

    row = GraphSubscription(
        id=uuid.uuid4(),
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        graph_subscription_id=graph_subscription_id,
        resource=f"users/synth-user/mailFolders/{folder.graph_folder_id}/messages",
        change_types="created,updated,deleted",
        notification_url="http://127.0.0.1:8000/webhooks/microsoft-graph/messages",
        lifecycle_notification_url="http://127.0.0.1:8000/webhooks/microsoft-graph/lifecycle",
        client_state_hash=hash_client_state(client_state),
        status=status,
        expiration_at=datetime(2026, 7, 27, tzinfo=UTC),
    )
    session.add(row)
    await session.flush()
    return row


# ------------------------------------------------------------------ factories


async def create_mailbox(
    session: AsyncSession, address: str = "astralicensing@astraglobal.com"
) -> Mailbox:
    mailbox = Mailbox(id=uuid.uuid4(), address=address.lower(), display_name="Test Mailbox")
    session.add(mailbox)
    await session.flush()
    return mailbox


async def create_email(
    session: AsyncSession,
    mailbox: Mailbox,
    *,
    graph_message_id: str | None = None,
    processing_state: str = "DISCOVERED",
    **overrides: Any,
) -> Email:
    email = Email(
        id=uuid.uuid4(),
        mailbox_id=mailbox.id,
        graph_message_id=graph_message_id or f"SYNTH-MSG-{uuid.uuid4().hex[:12]}",
        subject=overrides.pop("subject", "Test subject"),
        sender_email=overrides.pop("sender_email", "sender@example.invalid"),
        received_at=overrides.pop("received_at", datetime(2026, 7, 20, 12, 0, tzinfo=UTC)),
        processing_state=processing_state,
        **overrides,
    )
    session.add(email)
    await session.flush()
    return email
