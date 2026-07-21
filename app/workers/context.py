"""Shared runtime context for workers and CLI commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_engine, create_session_factory
from app.evidence.base import EvidenceStore
from app.evidence.filesystem import FilesystemEvidenceStore
from app.graph.auth import GraphTokenProvider, MsalConfidentialClientTokenProvider
from app.graph.client import GraphHttpClient


def build_evidence_store(settings: Settings) -> EvidenceStore:
    # Only the filesystem backend exists in Milestone 2; production startup
    # already rejects it via configuration validation.
    return FilesystemEvidenceStore(settings.filesystem_evidence_root)


def default_worker_id(settings: Settings) -> str:
    return settings.graph_worker_id or f"worker-{uuid.uuid4().hex[:8]}"


@dataclass
class WorkerContext:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    graph_client: GraphHttpClient
    evidence_store: EvidenceStore
    worker_id: str

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        worker_id: str | None = None,
        token_provider: GraphTokenProvider | None = None,
        graph_client: GraphHttpClient | None = None,
    ) -> WorkerContext:
        engine = create_engine(settings)
        provider = token_provider or MsalConfidentialClientTokenProvider(settings)
        return cls(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            graph_client=graph_client or GraphHttpClient(settings, provider),
            evidence_store=build_evidence_store(settings),
            worker_id=worker_id or default_worker_id(settings),
        )

    async def aclose(self) -> None:
        await self.graph_client.aclose()
        await self.engine.dispose()
