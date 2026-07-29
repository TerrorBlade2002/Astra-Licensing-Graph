"""Migration lifecycle and schema-drift tests."""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.models import Base

EXPECTED_TABLES = {
    "mailboxes",
    "mailbox_folders",
    "mailbox_sync_state",
    "emails",
    "email_recipients",
    "email_attachments",
    "classifications",
    "classification_reviews",
    "licensing_tasks",
    "task_requested_items",
    "outbound_drafts",
    "email_processing_events",
    "audit_events",
    "outbox_events",
    "sharepoint_sites",
    "sharepoint_drives",
    "sharepoint_folders",
    "sharepoint_sync_state",
    "sharepoint_upload_sessions",
    "documents",
    "document_versions",
    "document_links",
    "document_metadata_events",
    "document_jobs",
    "response_templates",
    "response_template_versions",
    "response_plans",
    "outbound_draft_versions",
    "outbound_draft_attachments",
    "send_approvals",
    "outbound_send_attempts",
    "message_move_attempts",
    "workflow_completion_records",
    "communication_jobs",
    "recipient_policy_rules",
}

EXPECTED_INDEXES = {
    "emails": {
        "uq_emails_internet_message_id",
        "ix_emails_state_received",
        "ix_emails_conversation_id",
        "ix_emails_next_retry_at",
    },
    "classifications": {"uq_classifications_current"},
    "email_attachments": {"uq_email_attachments_dedupe"},
    "email_processing_events": {
        "ix_email_processing_events_email_occurred",
        "ix_email_processing_events_correlation",
    },
    "mailboxes": {"uq_mailboxes_address_lower"},
}


def test_upgrade_head_creates_all_tables_and_indexes(
    migrated_database: None, test_database_url: str
) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _inspect() -> tuple[set[str], dict[str, set[str]]]:
        engine = create_async_engine(test_database_url)
        try:
            async with engine.connect() as conn:

                def collect(sync_conn):  # type: ignore[no-untyped-def]
                    inspector = inspect(sync_conn)
                    tables = set(inspector.get_table_names())
                    indexes = {
                        table: {ix["name"] for ix in inspector.get_indexes(table)}
                        for table in EXPECTED_INDEXES
                        if table in tables
                    }
                    return tables, indexes

                return await conn.run_sync(collect)
        finally:
            await engine.dispose()

    tables, indexes = asyncio.run(_inspect())
    assert tables >= EXPECTED_TABLES
    for table, expected in EXPECTED_INDEXES.items():
        assert expected <= indexes[table], f"missing indexes on {table}"


def test_downgrade_base_and_upgrade_again(
    migrated_database: None, alembic_config: Config, test_database_url: str
) -> None:
    command.downgrade(alembic_config, "base")
    try:
        import asyncio

        from sqlalchemy.ext.asyncio import create_async_engine

        async def _tables() -> set[str]:
            engine = create_async_engine(test_database_url)
            try:
                async with engine.connect() as conn:
                    return await conn.run_sync(
                        lambda sync_conn: set(inspect(sync_conn).get_table_names())
                    )
            finally:
                await engine.dispose()

        remaining = asyncio.run(_tables())
        assert not (EXPECTED_TABLES & remaining)
    finally:
        command.upgrade(alembic_config, "head")


def test_no_drift_between_metadata_and_migrations(
    migrated_database: None, test_database_url: str
) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _diff() -> list[object]:
        engine = create_async_engine(test_database_url)
        try:
            async with engine.connect() as conn:

                def compare(sync_conn):  # type: ignore[no-untyped-def]
                    context = MigrationContext.configure(
                        sync_conn,
                        opts={"compare_type": True, "compare_server_default": True},
                    )
                    return compare_metadata(context, Base.metadata)

                return await conn.run_sync(compare)
        finally:
            await engine.dispose()

    diff = asyncio.run(_diff())
    assert diff == [], f"schema drift detected: {diff}"
