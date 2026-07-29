import pytest
from jinja2 import UndefinedError
from pydantic import ValidationError

from app.auth.roles import Role, has_role
from app.communications.enums import ReadinessStatus
from app.communications.hashes import approval_snapshot_hash, recipient_set_hash
from app.communications.readiness import ResponseReadinessService
from app.communications.recipients import RecipientPolicyService
from app.communications.rendering import ResponseTemplateRenderer
from app.services.graph_draft_service import _attachment_identities
from tests.conftest import make_test_settings


def test_sender_is_not_inherited_by_admin() -> None:
    assert not has_role((Role.ADMIN.value,), Role.SENDER)
    assert has_role((Role.SENDER.value,), Role.SENDER)
    assert has_role((Role.MANAGER.value,), Role.SENDER)


def test_template_is_strict_deterministic_and_sandboxed() -> None:
    renderer = ResponseTemplateRenderer()
    first = renderer.render(
        subject_template="Re: {{ response_reference }}",
        text_template="Hello {{ vendor_name }}",
        html_template=None,
        allowed_variables=["response_reference", "vendor_name"],
        values={"response_reference": "ABC", "vendor_name": "RASI"},
    )
    second = renderer.render(
        subject_template="Re: {{ response_reference }}",
        text_template="Hello {{ vendor_name }}",
        html_template=None,
        allowed_variables=["response_reference", "vendor_name"],
        values={"response_reference": "ABC", "vendor_name": "RASI"},
    )
    assert first == second
    with pytest.raises(UndefinedError):
        renderer.render(
            subject_template=None,
            text_template="{{ vendor_name }} {{ jurisdiction }}",
            html_template=None,
            allowed_variables=["vendor_name", "jurisdiction"],
            values={"vendor_name": "RASI"},
        )
    with pytest.raises(ValueError, match="forbidden"):
        renderer.validate_template("{{ value.upper() }}", ["value"])
    with pytest.raises(ValueError, match="placeholder"):
        renderer.render(
            subject_template=None,
            text_template="[TODO]",
            html_template=None,
            allowed_variables=[],
            values={},
        )


def test_reply_all_bcc_blocklist_and_limits_are_hard_blocks() -> None:
    settings = make_test_settings(
        "postgresql+asyncpg://u:p@localhost/db",
        COMMUNICATION_REPLY_ALL_ENABLED=False,
        COMMUNICATION_BCC_ENABLED=False,
        COMMUNICATION_MAX_TOTAL_RECIPIENTS=2,
    )
    result = RecipientPolicyService(settings).evaluate(
        mode="REPLY_ALL",
        to_recipients=[{"address": "a@example.com"}],
        cc_recipients=[{"address": "b@blocked.example"}],
        bcc_recipients=[{"address": "c@example.com"}],
        blocked_domains={"blocked.example"},
    )
    assert not result.allowed
    assert set(result.blockers) >= {
        "REPLY_ALL_NOT_APPROVED",
        "BCC_NOT_AUTHORIZED",
        "RECIPIENT_POLICY_BLOCK",
    }


def test_approval_snapshot_changes_for_any_material_mutation() -> None:
    base = {
        "subject": "Re: Test",
        "body_sha256": "body",
        "recipient_sha256": recipient_set_hash([{"address": "a@example.com"}], [], []),
        "attachment_sha256": "attachments",
        "revision": 2,
        "graph_draft_message_id": "immutable-id",
        "graph_change_key": "ck1",
        "graph_etag": "etag1",
        "response_plan_id": "plan",
        "template_version_id": "template-v1",
    }
    approved = approval_snapshot_hash(**base)
    assert approval_snapshot_hash(**(base | {"subject": "Re: Changed"})) != approved
    assert approval_snapshot_hash(**(base | {"body_sha256": "changed"})) != approved
    assert approval_snapshot_hash(**(base | {"recipient_sha256": "changed"})) != approved
    assert approval_snapshot_hash(**(base | {"revision": 3})) != approved
    assert approval_snapshot_hash(**(base | {"graph_draft_message_id": "other"})) != approved
    assert approval_snapshot_hash(**(base | {"graph_change_key": "ck2"})) != approved
    assert approval_snapshot_hash(**(base | {"graph_etag": "etag2"})) != approved
    assert approval_snapshot_hash(**(base | {"attachment_sha256": "changed"})) != approved
    assert approval_snapshot_hash(**(base | {"template_version_id": "template-v2"})) != approved


def test_graph_attachment_identity_detects_outlook_replacement() -> None:
    approved = _attachment_identities(
        [{"id": "attachment-1", "name": "license.pdf", "size": 12, "isInline": False}]
    )
    replaced = _attachment_identities(
        [{"id": "attachment-2", "name": "license.pdf", "size": 12, "isInline": False}]
    )
    assert approved != replaced


def test_readiness_keeps_acknowledgement_distinct_from_final_response() -> None:
    service = ResponseReadinessService()
    acknowledgement = service.evaluate(
        response_type="ACKNOWLEDGEMENT",
        requested_item_statuses=["OPEN"],
        recipient_count=1,
    )
    final = service.evaluate(
        response_type="INFORMATION_RESPONSE",
        requested_item_statuses=["OPEN"],
        recipient_count=1,
    )
    assert acknowledgement.status == ReadinessStatus.READY_FOR_DRAFT
    assert final.status == ReadinessStatus.NOT_READY
    assert "REQUESTED_ITEM_NOT_VERIFIED" in final.blockers


def test_no_response_required_skips_send_readiness() -> None:
    result = ResponseReadinessService().evaluate(
        response_type="NO_RESPONSE_REQUIRED",
        requested_item_statuses=[],
        recipient_count=0,
    )
    assert result.status == ReadinessStatus.NOT_REQUIRED


@pytest.mark.parametrize(
    ("unsafe_setting", "value"),
    [
        ("GRAPH_SEND_ENABLED", True),
        ("COMMUNICATION_LARGE_ATTACHMENTS_ENABLED", True),
        ("COMMUNICATION_BCC_ENABLED", True),
    ],
)
def test_unsafe_communication_features_fail_closed(unsafe_setting: str, value: bool) -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            "postgresql+asyncpg://u:p@localhost/db",
            **{unsafe_setting: value},
        )


def test_shared_mailbox_large_attachment_path_requires_recorded_acceptance() -> None:
    settings = make_test_settings(
        "postgresql+asyncpg://u:p@localhost/db",
        COMMUNICATION_LARGE_ATTACHMENTS_ENABLED=True,
        COMMUNICATION_SHARED_MAILBOX_LARGE_ATTACHMENT_ACCEPTED=True,
    )
    assert settings.communication_large_attachments_enabled
    assert settings.communication_shared_mailbox_large_attachment_accepted
