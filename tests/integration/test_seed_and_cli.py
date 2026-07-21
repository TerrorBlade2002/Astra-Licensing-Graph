"""Seed command and importer CLI entry-point tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import import_prototype
from app.cli.seed_dev import seed
from app.core.config import get_settings
from app.models import Email
from tests.fixtures.prototype_builder import MAILBOX, build_prototype_tree


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    assert await seed(session) == "seeded"
    await session.commit()
    assert await seed(session) == "already-seeded"
    count = await session.scalar(select(func.count(Email.id)))
    assert count == 1


def test_import_cli_main_end_to_end(
    migrated_database: None,
    test_database_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_prototype_tree(tmp_path, ["CLI001"])
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    try:
        exit_code = import_prototype.main(
            ["--root", str(tmp_path), "--mailbox", MAILBOX, "--dry-run"]
        )
    finally:
        get_settings.cache_clear()
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["counts"]["errors"] == 0
    # Machine-readable report never includes body content.
    assert "body" not in json.dumps(report).lower()
