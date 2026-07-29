"""Stable hashes binding approval to the exact reviewable snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def sha256_text(value: str | None) -> str:
    normalized = re.sub(r"\r\n?", "\n", value or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalize_recipients(recipients: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for recipient in recipients:
        address = str(recipient.get("address") or "").strip().lower()
        name = str(recipient.get("name") or "").strip()
        normalized.append({"address": address, "name": name})
    return sorted(normalized, key=lambda item: (item["address"], item["name"]))


def recipient_set_hash(
    to_recipients: list[dict[str, Any]],
    cc_recipients: list[dict[str, Any]],
    bcc_recipients: list[dict[str, Any]],
) -> str:
    return canonical_sha256(
        {
            "to": normalize_recipients(to_recipients),
            "cc": normalize_recipients(cc_recipients),
            "bcc": normalize_recipients(bcc_recipients),
        }
    )


def attachment_set_hash(manifest: list[dict[str, Any]]) -> str:
    safe = [
        {
            "document_version_id": str(item.get("document_version_id") or ""),
            "filename": str(item.get("filename") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "content_sha256": str(item.get("content_sha256") or ""),
        }
        for item in manifest
    ]
    return canonical_sha256(
        sorted(safe, key=lambda item: (item["filename"], item["content_sha256"]))
    )


def approval_snapshot_hash(
    *,
    subject: str,
    body_sha256: str,
    recipient_sha256: str,
    attachment_sha256: str,
    revision: int,
    graph_draft_message_id: str,
    graph_change_key: str | None,
    graph_etag: str | None,
    response_plan_id: str,
    template_version_id: str | None,
) -> str:
    return canonical_sha256(
        {
            "subject": subject.strip(),
            "body_sha256": body_sha256,
            "recipient_set_sha256": recipient_sha256,
            "attachment_set_sha256": attachment_sha256,
            "revision": revision,
            "graph_draft_message_id": graph_draft_message_id,
            "graph_change_key": graph_change_key,
            "graph_etag": graph_etag,
            "response_plan_id": response_plan_id,
            "template_version_id": template_version_id,
        }
    )
