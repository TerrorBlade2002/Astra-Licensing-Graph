"""Filename safety and filesystem evidence-store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.evidence.filenames import sanitize_filename, stored_attachment_filename
from app.evidence.filesystem import FilesystemEvidenceStore
from app.evidence.hashing import sha256_hex
from app.graph.errors import EvidenceLimitExceededError


@pytest.mark.parametrize(
    ("raw", "expected_safe"),
    [
        ("report.pdf", "report.pdf"),
        ("..\\..\\windows\\system32\\evil.exe", "evil.exe"),
        ("../../../etc/passwd", "passwd"),
        ("dir/sub/file.csv", "file.csv"),
        ("  spaced .pdf", "spaced .pdf"),
        ('inva<l>id:"chars".txt', "inva_l_id__chars_.txt"),
        ("", "attachment"),
        (None, "attachment"),
        ("...", "attachment"),
        ("CON", "_CON"),
        ("com1.txt", "_com1.txt"),
    ],
)
def test_sanitize_filename(raw: str | None, expected_safe: str) -> None:
    assert sanitize_filename(raw) == expected_safe


def test_sanitize_truncates_very_long_names() -> None:
    long_name = "a" * 500 + ".pdf"
    safe = sanitize_filename(long_name)
    assert len(safe) <= 120
    assert safe.endswith(".pdf")


def test_stored_filename_is_collision_resistant() -> None:
    name = stored_attachment_filename("uuid-123", "invoice.pdf")
    assert name == "uuid-123_invoice.pdf"


async def test_put_bytes_and_read_back(tmp_path: Path) -> None:
    store = FilesystemEvidenceStore(tmp_path)
    data = b"synthetic evidence content"
    result = await store.put_bytes("mailboxes/m1/emails/e1/message.json", data)
    assert result.bytes_written == len(data)
    assert result.sha256_checksum == sha256_hex(data)
    assert result.storage_uri.startswith("file:///")
    assert await store.exists("mailboxes/m1/emails/e1/message.json")
    assert await store.open("mailboxes/m1/emails/e1/message.json") == data
    meta = await store.metadata("mailboxes/m1/emails/e1/message.json")
    assert meta is not None and meta.size_bytes == len(data)


async def test_put_stream_enforces_limit_and_leaves_no_partial_file(tmp_path: Path) -> None:
    store = FilesystemEvidenceStore(tmp_path)

    async def big_stream():
        for _ in range(10):
            yield b"x" * 1024

    with pytest.raises(EvidenceLimitExceededError):
        await store.put_stream("k/large.bin", big_stream(), max_bytes=4096)
    assert not await store.exists("k/large.bin")
    leftovers = list((tmp_path / "k").glob(".tmp-*")) if (tmp_path / "k").exists() else []
    assert leftovers == []


async def test_traversal_keys_are_rejected(tmp_path: Path) -> None:
    store = FilesystemEvidenceStore(tmp_path / "root")
    with pytest.raises(ValueError, match="escapes"):
        await store.put_bytes("../outside.bin", b"nope")


async def test_delete_and_missing_metadata(tmp_path: Path) -> None:
    store = FilesystemEvidenceStore(tmp_path)
    await store.put_bytes("a/b.txt", b"1")
    await store.delete("a/b.txt")
    assert not await store.exists("a/b.txt")
    assert await store.metadata("a/b.txt") is None
