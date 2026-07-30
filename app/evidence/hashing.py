"""Streaming SHA-256 helper."""

from __future__ import annotations

import hashlib


class StreamingSha256:
    def __init__(self) -> None:
        self._hasher = hashlib.sha256()
        self.bytes_seen = 0

    def update(self, chunk: bytes) -> None:
        self._hasher.update(chunk)
        self.bytes_seen += len(chunk)

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
