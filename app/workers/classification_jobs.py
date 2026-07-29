"""Durable CLASSIFY_EMAIL worker handler."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_provider import OpenAIClassificationProvider
from app.classification.orchestration import ClassificationOrchestrator
from app.models import GraphJob
from app.workers.context import WorkerContext


async def handle_classification_job(
    ctx: WorkerContext, session: AsyncSession, job: GraphJob
) -> None:
    if job.email_id is None:
        raise ValueError("CLASSIFY_EMAIL job is missing email_id")
    provider = (
        OpenAIClassificationProvider(ctx.settings)
        if ctx.settings.ai_classification_enabled
        else None
    )
    try:
        await ClassificationOrchestrator(session, ctx.settings, provider).classify_email(
            job.email_id, reclassification=bool(job.payload.get("reclassification"))
        )
    finally:
        if provider is not None:
            await provider.aclose()
