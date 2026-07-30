"""Shared runtime context for workers and CLI commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_engine, create_session_factory
from app.evidence.base import EvidenceStore
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.r2 import R2EvidenceStore
from app.evidence.sharepoint import SharePointEvidenceStore
from app.graph.auth import GraphTokenProvider, MsalConfidentialClientTokenProvider
from app.graph.client import GraphHttpClient
from app.sharepoint.client import SharePointClient


def build_evidence_store(settings: Settings, graph_client: GraphHttpClient) -> EvidenceStore:
    if settings.evidence_storage_backend == "filesystem":
        return FilesystemEvidenceStore(settings.filesystem_evidence_root)
    if settings.evidence_storage_backend == "r2":
        return R2EvidenceStore(settings)
    if not settings.sharepoint_site_id or not settings.sharepoint_working_documents_drive_id:
        raise ValueError("SharePoint evidence requires site and working-document drive IDs")
    client = SharePointClient(graph_client, settings)
    return SharePointEvidenceStore(
        client,
        site_id=settings.sharepoint_site_id,
        default_drive_id=settings.sharepoint_working_documents_drive_id,
    )


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
        resolved_graph_client = graph_client or GraphHttpClient(settings, provider)
        return cls(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            graph_client=resolved_graph_client,
            evidence_store=build_evidence_store(settings, resolved_graph_client),
            worker_id=worker_id or default_worker_id(settings),
        )

    async def aclose(self) -> None:
        if isinstance(self.evidence_store, SharePointEvidenceStore):
            await self.evidence_store.client.aclose()
        await self.graph_client.aclose()
        await self.engine.dispose()
