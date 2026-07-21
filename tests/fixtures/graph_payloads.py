"""Synthetic Microsoft Graph payload builders for mocked tests.

No real Astra identifiers, Graph IDs, tenants, or secrets appear here.
"""

from __future__ import annotations

from typing import Any

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SYNTH_TENANT = "00000000-0000-0000-0000-00000000t3st"


def subscription_created_response(
    *, subscription_id: str = "synth-sub-001", resource: str = "users/x/mailFolders/f/messages"
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "resource": resource,
        "changeType": "created,updated,deleted",
        "expirationDateTime": "2026-07-27T00:00:00.000Z",
        "notificationUrl": "http://127.0.0.1:8000/webhooks/microsoft-graph/messages",
    }


def notification_item(
    *,
    subscription_id: str,
    client_state: str | None,
    notification_id: str | None = "synth-notif-001",
    change_type: str = "created",
    lifecycle_event: str | None = None,
    tenant_id: str = SYNTH_TENANT,
    resource: str = "Users/synth-user/Messages/SYNTH-MSG-001",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "subscriptionId": subscription_id,
        "subscriptionExpirationDateTime": "2026-07-27T00:00:00.000Z",
        "tenantId": tenant_id,
        "resource": resource,
        "clientState": client_state,
    }
    if notification_id:
        item["id"] = notification_id
    if lifecycle_event:
        item["lifecycleEvent"] = lifecycle_event
    else:
        item["changeType"] = change_type
    return item


def delta_message(
    *,
    graph_message_id: str = "SYNTH-MSG-001",
    subject: str = "Synthetic renewal notice",
    received: str = "2026-07-21T10:00:00Z",
    has_attachments: bool = False,
    is_read: bool = False,
) -> dict[str, Any]:
    return {
        "id": graph_message_id,
        "subject": subject,
        "from": {"emailAddress": {"name": "Synthetic Sender", "address": "Sender@Example.invalid"}},
        "toRecipients": [
            {
                "emailAddress": {
                    "name": "Astra Licensing",
                    "address": "astralicensing@astraglobal.com",
                }
            }
        ],
        "ccRecipients": [],
        "receivedDateTime": received,
        "bodyPreview": "Synthetic preview",
        "hasAttachments": has_attachments,
        "conversationId": "SYNTH-CONV-001",
        "internetMessageId": f"<{graph_message_id}@synthetic.invalid>",
        "isRead": is_read,
        "parentFolderId": "SYNTH-FOLDER-INBOX",
        "lastModifiedDateTime": received,
        "@odata.etag": 'W/"synthetic"',
    }


def delta_removed(graph_message_id: str) -> dict[str, Any]:
    return {"id": graph_message_id, "@removed": {"reason": "changed"}}


def delta_page(
    items: list[dict[str, Any]],
    *,
    next_link: str | None = None,
    delta_link: str | None = None,
) -> dict[str, Any]:
    page: dict[str, Any] = {"value": items}
    if next_link:
        page["@odata.nextLink"] = next_link
    if delta_link:
        page["@odata.deltaLink"] = delta_link
    return page


def delta_link_url(token: str = "synthDeltaToken001") -> str:
    return (
        f"{GRAPH_BASE}/users/synth-user/mailFolders/SYNTH-FOLDER-INBOX/"
        f"messages/delta?$deltatoken={token}"
    )


def next_link_url(token: str = "synthSkipToken001") -> str:
    return (
        f"{GRAPH_BASE}/users/synth-user/mailFolders/SYNTH-FOLDER-INBOX/"
        f"messages/delta?$skiptoken={token}"
    )


def full_message(
    *,
    graph_message_id: str = "SYNTH-MSG-001",
    has_attachments: bool = False,
    body_content: str = "Synthetic body text for evidence.",
) -> dict[str, Any]:
    message = delta_message(graph_message_id=graph_message_id, has_attachments=has_attachments)
    message.update(
        {
            "bccRecipients": [],
            "replyTo": [],
            "sentDateTime": "2026-07-21T09:59:00Z",
            "body": {"contentType": "text", "content": body_content},
        }
    )
    return message


def file_attachment_meta(
    *,
    attachment_id: str = "SYNTH-ATT-001",
    name: str = "renewal.pdf",
    content_type: str = "application/pdf",
    size: int = 2048,
    is_inline: bool = False,
) -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": attachment_id,
        "name": name,
        "contentType": content_type,
        "size": size,
        "isInline": is_inline,
        "lastModifiedDateTime": "2026-07-21T10:00:00Z",
    }


def item_attachment_meta(*, attachment_id: str = "SYNTH-ATT-ITEM") -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.itemAttachment",
        "id": attachment_id,
        "name": "Forwarded synthetic message",
        "contentType": "message/rfc822",
        "size": 1024,
        "isInline": False,
    }


def reference_attachment_meta(*, attachment_id: str = "SYNTH-ATT-REF") -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.referenceAttachment",
        "id": attachment_id,
        "name": "Shared cloud file",
        "contentType": None,
        "size": 0,
        "isInline": False,
    }
