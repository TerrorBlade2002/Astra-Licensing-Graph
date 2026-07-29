"""Seed one pending, synthetic Milestone 4 review for local portal testing."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.classification.orchestration import ClassificationOrchestrator
from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.models import Email, LicensingTask, Mailbox
from app.services.response_template_service import ResponseTemplateService

GRAPH_ID = "SYNTH-M4-REVIEW-0001"


async def run(*, reset: bool = False) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            existing = await session.scalar(select(Email).where(Email.graph_message_id == GRAPH_ID))
            if existing and reset:
                await session.execute(
                    delete(LicensingTask).where(LicensingTask.email_id == existing.id)
                )
                await session.execute(delete(Email).where(Email.id == existing.id))
                await session.commit()
                existing = None
            if existing:
                print(existing.id)
                return 0
            mailbox = await session.scalar(
                select(Mailbox).where(Mailbox.address == "astralicensing@astraglobal.com")
            )
            if mailbox is None:
                mailbox = Mailbox(
                    address="astralicensing@astraglobal.com",
                    display_name="Astra Licensing",
                    is_active=True,
                )
                session.add(mailbox)
                await session.flush()
            email = Email(
                id=uuid.uuid4(),
                mailbox_id=mailbox.id,
                graph_message_id=GRAPH_ID,
                subject="Colorado Collection Agency License renewal — information required",
                sender_name="RASI Licensing Team",
                sender_email="renewals@rasi.com",
                received_at=datetime(2026, 7, 22, 13, 30, tzinfo=UTC),
                body_content_type="text",
                body_text=(
                    "Hello Astra Licensing,\n\nPlease provide:\n"
                    "- Current toll-free telephone number\n"
                    "- Copy of the current officer report\n\n"
                    "The requested information is due by July 31, 2026.\n\nThank you."
                ),
                body_preview="Please provide the current toll-free telephone number...",
                has_attachments=False,
                processing_state="ATTACHMENTS_SAVED",
            )
            session.add(email)
            await session.commit()
            classification = await ClassificationOrchestrator(session, settings).classify_email(
                email.id
            )
            await ResponseTemplateService(session).ensure_defaults("seed-milestone4-cli")
            print(classification.id)
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Replace only the synthetic M4 row.")
    return asyncio.run(run(reset=parser.parse_args().reset))


if __name__ == "__main__":
    raise SystemExit(main())
