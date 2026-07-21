"""Builds synthetic prototype directory trees mirroring the PowerShell layout.

All IDs are clearly synthetic; no real Graph identifiers or mailbox content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAILBOX = "astralicensing@astraglobal.com"

FULL_HISTORY = [
    {
        "from_state": None,
        "to_state": "DISCOVERED",
        "occurred_at": "2026-07-20T20:39:05.0217055Z",
        "note": "Message reported by Inbox delta query.",
        "error_code": None,
        "error_message": None,
    },
    {
        "from_state": "DISCOVERED",
        "to_state": "FETCHED",
        "occurred_at": "2026-07-20T20:39:05.3201727Z",
        "note": "Structured Graph message and raw MIME were saved.",
        "error_code": "",
        "error_message": "",
    },
    {
        "from_state": "FETCHED",
        "to_state": "ATTACHMENTS_SAVED",
        "occurred_at": "2026-07-20T20:39:05.4283741Z",
        "note": "Attachment inspection completed.",
        "error_code": "",
        "error_message": "",
    },
    {
        "from_state": "ATTACHMENTS_SAVED",
        "to_state": "CLASSIFIED",
        "occurred_at": "2026-07-20T22:19:08.8578371Z",
        "note": "Validated classification schema saved.",
        "error_code": None,
        "error_message": None,
    },
    {
        "from_state": "CLASSIFIED",
        "to_state": "TASK_CREATED",
        "occurred_at": "2026-07-21T15:39:59.9497952Z",
        "note": "Human review completed with decision APPROVED.",
        "error_code": None,
        "error_message": None,
    },
    {
        "from_state": "TASK_CREATED",
        "to_state": "MOVED",
        "occurred_at": "2026-07-21T17:26:47.2615208Z",
        "note": "Graph moved the source message.",
        "error_code": None,
        "error_message": None,
    },
    {
        "from_state": "MOVED",
        "to_state": "COMPLETED",
        "occurred_at": "2026-07-21T17:26:47.3747309Z",
        "note": "Workflow committed.",
        "error_code": None,
        "error_message": None,
    },
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig mirrors PowerShell's BOM-prefixed output.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8-sig")


def state_record(record_key: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_key": record_key,
        "mailbox_address": MAILBOX,
        "internet_message_id": f"<{record_key}@synthetic.invalid>",
        "conversation_id": f"SYNTH-CONV-{record_key}",
        "subject": "Colorado Collection Agency License Renewal - Information Required",
        "sender_email": "synthetic.sender@example.invalid",
        "received_at": "2026-07-20T20:37:46Z",
        "graph_message_id": f"SYNTH-MSG-{record_key}",
        "retry_count": 0,
        "discovered_at": "2026-07-20T20:39:05.0217055Z",
        "task_id": f"LIC-{record_key}",
        "draft_required": True,
        "draft_message_id": f"SYNTH-DRAFT-{record_key}",
        "draft_status": "SENT",
        "draft_sent_at": "2026-07-21T17:08:42.9362730Z",
        "destination_folder_id": f"SYNTH-FOLDER-{record_key}",
        "destination_folder_name": "08_Info_Required",
        "current_state": "COMPLETED",
        "completed_at": "2026-07-21T17:26:47.2439382Z",
        "reviewer": "reviewer@example.invalid",
        "history": FULL_HISTORY,
    }
    record.update(overrides)
    return record


def message_json(record_key: str) -> dict[str, Any]:
    return {
        "id": f"SYNTH-MSG-{record_key}",
        "receivedDateTime": "2026-07-20T20:37:46Z",
        "sentDateTime": "2026-07-20T20:37:44Z",
        "hasAttachments": True,
        "internetMessageId": f"<{record_key}@synthetic.invalid>",
        "subject": "Colorado Collection Agency License Renewal - Information Required",
        "bodyPreview": "Synthetic preview",
        "conversationId": f"SYNTH-CONV-{record_key}",
        "isRead": False,
        "body": {"contentType": "text", "content": "Synthetic body text."},
        "from": {
            "emailAddress": {
                "name": "Synthetic Sender",
                "address": "Synthetic.Sender@Example.invalid",
            }
        },
        "toRecipients": [{"emailAddress": {"name": "Astra Licensing", "address": MAILBOX}}],
        "ccRecipients": [{"emailAddress": {"name": "CC Person", "address": "cc@example.invalid"}}],
        "bccRecipients": [],
    }


def classification_json(record_key: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "record_key": record_key,
        "vendor": "RASI",
        "email_type": "missing_information_request",
        "states": ["Colorado"],
        "license_types": ["Collection Agency License"],
        "license_numbers": ["CO-CA-12345"],
        "action_required": True,
        "requested_information": ["Item one", "Item two"],
        "documents": [],
        "due_date": "2026-07-31",
        "summary": "Synthetic summary.",
        "proposed_action": "Provide the requested information.",
        "confidence": 0.95,
        "requires_human_review": True,
        "classification_method": "deterministic_rules_plus_llm",
        "rule_matches": ["information required"],
        "llm": {
            "status": "SUCCEEDED",
            "error": None,
            "model": "synthetic-model",
            "requested": True,
        },
        "evidence": {
            "subject": "Synthetic subject",
            "raw_message_json": "C:\\synthetic\\message.json",
        },
        "classified_at": "2026-07-21T14:57:33.8205816Z",
    }


def review_json(record_key: str) -> dict[str, Any]:
    return {
        "review_schema_version": "1.0",
        "record_key": record_key,
        "decision": "APPROVED",
        "reviewer": "reviewer@example.invalid",
        "reviewed_at": "2026-07-21T15:39:59.8500438Z",
        "review_notes": "",
        "reviewed_classification": classification_json(record_key),
    }


def task_json(record_key: str) -> dict[str, Any]:
    return {
        "task_schema_version": "1.0",
        "task_id": f"LIC-{record_key}",
        "record_key": record_key,
        "title": "Colorado - Collection Agency License - missing information request",
        "queue": "08_Info_Required",
        "destination_folder_name": "08_Info_Required",
        "destination_folder_id": f"SYNTH-FOLDER-{record_key}",
        "vendor": "RASI",
        "email_type": "missing_information_request",
        "requested_information": ["Item one", "Item two"],
        "due_date": "2026-07-31",
        "proposed_action": "Provide the requested information.",
        "draft_required": True,
        "draft_status": "SENT",
        "status": "COMPLETED",
        "created_at": "2026-07-21T15:39:59.8500438Z",
        "completed_at": "2026-07-21T17:26:47.2439382Z",
    }


def attachment_manifest(record_key: str) -> list[dict[str, Any]]:
    return [
        {
            "attachment_id": f"SYNTH-ATT-{record_key}",
            "attachment_type": "#microsoft.graph.fileAttachment",
            "original_filename": "synthetic.csv",
            "stored_filename": "01_synthetic.csv",
            "mime_type": "text/csv",
            "graph_size_bytes": 100,
            "local_size_bytes": 90,
            "is_inline": False,
            "storage_path": "C:\\synthetic\\01_synthetic.csv",
            "sha256_checksum": "AB" * 32,
            "status": "DOWNLOADED",
            "downloaded_at": "2026-07-20T19:34:30.3606095Z",
        }
    ]


def build_prototype_tree(
    root: Path,
    record_keys: list[str],
    *,
    state_wrapper: str = "array",
    include_folders: bool = True,
    broken_keys: set[str] | None = None,
) -> None:
    """Write a full prototype tree for the given records.

    state_wrapper: 'array' | 'single' | 'nested' | 'wrapper' controls the
    JSON shape of email_processing_state.json.
    """
    broken_keys = broken_keys or set()
    records = [state_record(key) for key in record_keys]

    payload: Any
    if state_wrapper == "single" and len(records) == 1:
        payload = records[0]
    elif state_wrapper == "nested":
        payload = [records]
    elif state_wrapper == "wrapper":
        payload = {"records": records}
    else:
        payload = records
    write_json(root / "processing" / "state" / "email_processing_state.json", payload)

    if include_folders:
        write_json(
            root / "mailbox_folders.json",
            [
                {
                    "mailbox_address": MAILBOX,
                    "graph_folder_id": "SYNTH-FOLDER-INBOX",
                    "display_name": "Inbox",
                    "folder_path": "Inbox",
                    "is_hidden": False,
                    "purpose": "Intake",
                    "last_verified_at": "2026-07-20T17:02:23.0144838Z",
                },
                {
                    "mailbox_address": MAILBOX,
                    "graph_folder_id": "SYNTH-FOLDER-08",
                    "display_name": "08_Info_Required",
                    "folder_path": "08_Info_Required",
                    "is_hidden": False,
                    "purpose": "Information requests",
                    "last_verified_at": "2026-07-20T17:02:23.0306447Z",
                },
            ],
        )

    for key in record_keys:
        if key in broken_keys:
            # Malformed message.json: not valid JSON at all.
            path = root / "processing" / "raw-emails" / key / "message.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{ this is not json", encoding="utf-8-sig")
            continue
        write_json(root / "processing" / "raw-emails" / key / "message.json", message_json(key))
        (root / "processing" / "raw-emails" / key / "message.eml").write_text(
            "MIME-Version: 1.0\r\nSubject: synthetic\r\n\r\nSynthetic body.",
            encoding="utf-8",
        )
        write_json(
            root / "processing" / "attachments" / key / "attachment_manifest.json",
            attachment_manifest(key),
        )
        write_json(
            root / "processing" / "classifications" / key / "classification.json",
            classification_json(key),
        )
        write_json(root / "processing" / "reviews" / key / "review.json", review_json(key))
        write_json(root / "processing" / "tasks" / f"LIC-{key}.json", task_json(key))

    write_json(
        root / "processing" / "tasks" / "tasks_index.json",
        [task_json(key) for key in record_keys if key not in broken_keys],
    )
