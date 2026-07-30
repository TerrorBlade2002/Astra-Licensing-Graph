"""Cloudflare R2 evidence backend (S3-compatible).

SharePoint remains the governed repository of record. This backend exists so
the system keeps working when SharePoint is unavailable or not yet provisioned,
without falling back to a local filesystem that production forbids.

Two properties matter more than throughput here:

* **Content is hashed while streaming**, so the recorded SHA-256 is of the
  bytes actually stored, not of a buffer that was hashed separately.
* **A size limit is enforced during the stream**, not after, so an oversized
  object never lands in the bucket.

boto3 is synchronous, so every call runs in a worker thread; the event loop is
never blocked on network I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from functools import partial
from typing import TYPE_CHECKING, Any

from app.core.exceptions import DomainError
from app.evidence.base import EvidenceMetadata, EvidenceWriteResult
from app.evidence.hashing import StreamingSha256

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings


class R2ConfigurationError(DomainError):
    code = "r2_configuration_error"


class R2EvidenceStore:
    """Object storage backed by a Cloudflare R2 bucket."""

    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("R2_ACCOUNT_ID", settings.r2_account_id),
                ("R2_BUCKET", settings.r2_bucket),
                ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            )
            if not value
        ]
        if missing:
            raise R2ConfigurationError(
                "R2 storage requires " + ", ".join(missing),
            )
        self.settings = settings
        self.bucket = str(settings.r2_bucket)
        self._client: Any | None = None

    # boto3 is imported lazily so that installations which never enable R2 do
    # not pay the import cost, and so a missing extra fails loudly at use time.
    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard
            raise R2ConfigurationError(
                "R2 storage requires the boto3 dependency to be installed."
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self.settings.r2_endpoint_url,
            aws_access_key_id=self.settings.r2_access_key_id,
            aws_secret_access_key=self.settings.r2_secret_access_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=self.settings.r2_connect_timeout_seconds,
                read_timeout=self.settings.r2_read_timeout_seconds,
            ),
        )
        return self._client

    async def _call(self, operation: str, **kwargs: Any) -> Any:
        client = self._ensure_client()
        return await asyncio.to_thread(partial(getattr(client, operation), **kwargs))

    def _to_uri(self, key: str) -> str:
        return f"r2://{self.bucket}/{key}"

    @staticmethod
    def _validate_key(key: str) -> str:
        # Keys are built internally, but a traversal segment would still be a
        # silent cross-prefix write. Reject rather than normalise.
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"Invalid evidence key: {key!r}")
        return key

    async def put_bytes(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> EvidenceWriteResult:
        self._validate_key(key)
        hasher = StreamingSha256()
        hasher.update(data)
        await self._call(
            "put_object",
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            # Recorded as object metadata so the stored digest travels with the
            # object; the catalog keeps the authoritative copy.
            Metadata={"sha256": hasher.hexdigest()},
        )
        return EvidenceWriteResult(
            storage_uri=self._to_uri(key),
            bytes_written=hasher.bytes_seen,
            sha256_checksum=hasher.hexdigest(),
            content_type=content_type,
            upload_method="r2_put_object",
        )

    async def put_stream(
        self,
        key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int,
        content_type: str = "application/octet-stream",
    ) -> EvidenceWriteResult:
        """Buffer-bounded upload.

        Chunks accumulate only until the configured part size, then go out as a
        multipart part, so memory use stays flat regardless of object size.
        """
        self._validate_key(key)
        hasher = StreamingSha256()
        part_size = max(self.settings.r2_multipart_part_bytes, 5 * 1024 * 1024)

        created = await self._call(
            "create_multipart_upload",
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type,
        )
        upload_id = created["UploadId"]
        parts: list[dict[str, Any]] = []
        buffer = bytearray()
        try:
            async for chunk in stream:
                hasher.update(chunk)
                if hasher.bytes_seen > max_bytes:
                    raise DomainError(
                        f"Evidence exceeds the {max_bytes} byte limit for this store."
                    )
                buffer.extend(chunk)
                if len(buffer) >= part_size:
                    parts.append(await self._upload_part(key, upload_id, len(parts) + 1, buffer))
                    buffer.clear()
            if buffer or not parts:
                parts.append(await self._upload_part(key, upload_id, len(parts) + 1, buffer))
            await self._call(
                "complete_multipart_upload",
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except BaseException:
            # Never leave a half-written object: an abandoned multipart upload
            # is billable and would look like a partial evidence record.
            await self._abort(key, upload_id)
            raise

        return EvidenceWriteResult(
            storage_uri=self._to_uri(key),
            bytes_written=hasher.bytes_seen,
            sha256_checksum=hasher.hexdigest(),
            content_type=content_type,
            upload_method="r2_multipart",
        )

    async def _upload_part(
        self, key: str, upload_id: str, number: int, body: bytearray
    ) -> dict[str, Any]:
        result = await self._call(
            "upload_part",
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=number,
            Body=bytes(body),
        )
        return {"ETag": result["ETag"], "PartNumber": number}

    async def _abort(self, key: str, upload_id: str) -> None:
        # Cleanup is best effort: the original failure is what the caller needs
        # to see, so an abort error must not replace it.
        with contextlib.suppress(Exception):
            await self._call(
                "abort_multipart_upload", Bucket=self.bucket, Key=key, UploadId=upload_id
            )

    async def exists(self, key: str) -> bool:
        try:
            await self._call("head_object", Bucket=self.bucket, Key=self._validate_key(key))
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise
        return True

    async def open(self, key: str) -> bytes:
        result = await self._call("get_object", Bucket=self.bucket, Key=self._validate_key(key))
        body = result["Body"]
        return await asyncio.to_thread(body.read)

    async def delete(self, key: str) -> None:
        await self._call("delete_object", Bucket=self.bucket, Key=self._validate_key(key))

    async def metadata(self, key: str) -> EvidenceMetadata | None:
        try:
            head = await self._call("head_object", Bucket=self.bucket, Key=self._validate_key(key))
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        return EvidenceMetadata(
            storage_uri=self._to_uri(key),
            size_bytes=int(head.get("ContentLength", 0)),
            content_type=head.get("ContentType"),
        )


def _is_not_found(exc: BaseException) -> bool:
    """True for the several shapes botocore uses to say 'no such key'."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {})
        if str(error.get("Code")) in {"404", "NoSuchKey", "NotFound"}:
            return True
        if int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)) == 404:
            return True
    return type(exc).__name__ in {"NoSuchKey", "ClientError404"}
