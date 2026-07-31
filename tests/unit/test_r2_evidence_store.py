"""R2 evidence backend: hashing, limits, cleanup, and key safety.

No network access: a fake S3 client records the calls boto3 would have made.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.evidence.hashing import sha256_hex
from app.evidence.r2 import R2ConfigurationError, R2EvidenceStore, _is_not_found


class FakeS3:
    """Minimal stand-in recording the S3 operations the store performs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.objects: dict[str, bytes] = {}
        self.aborted: list[str] = []
        self.fail_on_part: int | None = None

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"etag"'}

    def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_multipart_upload", kwargs))
        return {"UploadId": "upload-1"}

    def upload_part(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("upload_part", kwargs))
        if self.fail_on_part == kwargs["PartNumber"]:
            raise RuntimeError("simulated part failure")
        self.objects.setdefault(kwargs["Key"], b"")
        self.objects[kwargs["Key"]] += kwargs["Body"]
        return {"ETag": f'"etag-{kwargs["PartNumber"]}"'}

    def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete_multipart_upload", kwargs))
        return {"ETag": '"final"'}

    def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.aborted.append(kwargs["Key"])
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["Key"] not in self.objects:
            raise _not_found()
        body = self.objects[kwargs["Key"]]
        return {"ContentLength": len(body), "ContentType": "application/pdf"}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.objects[kwargs["Key"]])}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.objects.pop(kwargs["Key"], None)
        return {}


def _not_found() -> Exception:
    error = Exception("not found")
    error.response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}  # type: ignore[attr-defined]
    return error


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5442/db",
        "R2_ACCOUNT_ID": "acct123",
        "R2_BUCKET": "astra-licensing-documents",
        "R2_ACCESS_KEY_ID": "synthetic-key-id",
        "R2_SECRET_ACCESS_KEY": "synthetic-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _store(client: FakeS3, **overrides: Any) -> R2EvidenceStore:
    store = R2EvidenceStore(_settings(**overrides))
    store._client = client
    return store


async def _stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def test_endpoint_is_derived_from_the_account() -> None:
    assert _settings().r2_endpoint_url == "https://acct123.r2.cloudflarestorage.com"


def test_incomplete_configuration_fails_before_any_request() -> None:
    """Naming the missing variables beats a signature error at upload time."""
    with pytest.raises(R2ConfigurationError, match="R2_BUCKET"):
        R2EvidenceStore(_settings(R2_BUCKET=None))


def test_selecting_r2_without_credentials_is_rejected_at_startup() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="R2_ACCESS_KEY_ID"):
        _settings(EVIDENCE_STORAGE_BACKEND="r2", R2_ACCESS_KEY_ID=None)


async def test_put_bytes_records_the_digest_of_what_was_stored() -> None:
    client = FakeS3()
    store = _store(client)
    payload = b"regulator confirmation"

    result = await store.put_bytes("documents/a.pdf", payload, content_type="application/pdf")

    assert result.sha256_checksum == sha256_hex(payload)
    assert result.bytes_written == len(payload)
    assert result.storage_uri == "r2://astra-licensing-documents/documents/a.pdf"
    assert client.objects["documents/a.pdf"] == payload


async def test_streamed_upload_hashes_the_concatenated_content() -> None:
    client = FakeS3()
    store = _store(client)

    result = await store.put_stream(
        "documents/b.pdf", _stream(b"part-one", b"part-two"), max_bytes=1_000
    )

    assert result.sha256_checksum == sha256_hex(b"part-onepart-two")
    assert client.objects["documents/b.pdf"] == b"part-onepart-two"
    assert result.upload_method == "r2_multipart"


async def test_oversized_stream_is_stopped_and_the_upload_is_abandoned() -> None:
    """The limit is enforced mid-stream, so nothing oversized is completed."""
    client = FakeS3()
    store = _store(client)

    with pytest.raises(DomainError, match="exceeds"):
        await store.put_stream("documents/big.pdf", _stream(b"x" * 50, b"y" * 50), max_bytes=60)

    assert client.aborted == ["documents/big.pdf"]
    assert not any(call[0] == "complete_multipart_upload" for call in client.calls)


async def test_a_failed_part_aborts_rather_than_leaving_a_partial_object() -> None:
    client = FakeS3()
    client.fail_on_part = 1
    store = _store(client)

    with pytest.raises(RuntimeError):
        await store.put_stream("documents/c.pdf", _stream(b"data"), max_bytes=1_000)

    assert client.aborted == ["documents/c.pdf"]


async def test_empty_stream_still_produces_one_part() -> None:
    """A zero-byte object is valid; a multipart upload with no parts is not."""
    client = FakeS3()
    store = _store(client)

    result = await store.put_stream("documents/empty.pdf", _stream(), max_bytes=10)

    assert result.bytes_written == 0
    assert sum(1 for call in client.calls if call[0] == "upload_part") == 1


@pytest.mark.parametrize("key", ["", "/leading", "documents/../escape", "../outside"])
async def test_keys_that_could_escape_their_prefix_are_rejected(key: str) -> None:
    store = _store(FakeS3())
    with pytest.raises(ValueError):
        await store.put_bytes(key, b"data")


async def test_missing_object_reads_as_absent_rather_than_erroring() -> None:
    store = _store(FakeS3())
    assert await store.exists("documents/none.pdf") is False
    assert await store.metadata("documents/none.pdf") is None


async def test_metadata_reports_size_and_type_for_a_stored_object() -> None:
    client = FakeS3()
    store = _store(client)
    await store.put_bytes("documents/d.pdf", b"12345", content_type="application/pdf")

    meta = await store.metadata("documents/d.pdf")

    assert meta is not None
    assert meta.size_bytes == 5
    assert meta.content_type == "application/pdf"


def test_not_found_detection_covers_botocore_shapes() -> None:
    assert _is_not_found(_not_found()) is True
    assert _is_not_found(RuntimeError("boom")) is False


# ------------------------------------------------- backend switch behaviour


def test_object_stored_versions_are_identifiable_and_carry_their_key() -> None:
    """Switching backends must not make old versions ambiguous.

    A version written to an object store records the object key in the same
    column SharePoint uses for its item id, so a later download resolves it
    without a second lookup table.
    """
    from app.models import DocumentVersion
    from app.services.document_content import version_is_object_stored
    from app.services.document_upload import OBJECT_STORE_SITE_SENTINEL

    object_version = DocumentVersion(
        graph_site_id=OBJECT_STORE_SITE_SENTINEL,
        graph_drive_id=OBJECT_STORE_SITE_SENTINEL,
        graph_drive_item_id="documents/licenses/abc123/file.pdf",
    )
    sharepoint_version = DocumentVersion(
        graph_site_id="contoso.sharepoint.com,guid,guid",
        graph_drive_id="b!drive",
        graph_drive_item_id="01ITEM",
    )

    assert version_is_object_stored(object_version) is True
    assert version_is_object_stored(sharepoint_version) is False
    assert object_version.graph_drive_item_id.endswith("file.pdf")


def test_source_store_follows_the_configured_backend() -> None:
    from app.evidence.filesystem import FilesystemEvidenceStore
    from app.services.document_content import source_store_for

    assert isinstance(source_store_for(_settings(EVIDENCE_STORAGE_BACKEND="r2")), R2EvidenceStore)
    assert isinstance(
        source_store_for(_settings(EVIDENCE_STORAGE_BACKEND="filesystem")),
        FilesystemEvidenceStore,
    )
