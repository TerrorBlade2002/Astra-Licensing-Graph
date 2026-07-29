import re

import respx
from httpx import Response
from sqlalchemy import select

from app.auth.actors import CurrentActor
from app.classification.orchestration import ClassificationOrchestrator
from app.communications.enums import CommunicationDraftStatus, MoveAttemptStatus
from app.communications.hashes import approval_snapshot_hash
from app.communications.snapshots import create_version
from app.domain.enums import ActorType
from app.graph.client import GraphHttpClient
from app.models import (
    ClassificationReview,
    Email,
    MailboxFolder,
    ResponseTemplate,
    ResponseTemplateVersion,
    SendApproval,
)
from app.services.communication_enqueue_service import CommunicationEnqueueService
from app.services.draft_generation_service import DraftGenerationService
from app.services.draft_review_service import DraftReviewService
from app.services.graph_draft_service import GraphDraftService
from app.services.outbound_send_service import OutboundSendService
from app.services.response_plan_service import ResponsePlanService
from app.services.response_template_service import ResponseTemplateService
from app.services.send_approval_service import SendApprovalService
from app.services.sent_reconciliation_service import SentReconciliationService
from app.services.source_move_service import SourceMoveService
from app.services.workflow_completion_service import WorkflowCompletionService
from app.tasks.creation import TaskCreationService
from tests.conftest import FakeTokenProvider, create_email, create_mailbox, make_test_settings


def actor(actor_id: str, *roles: str) -> CurrentActor:
    return CurrentActor(
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        tenant_id="test",
        object_id=actor_id,
        roles=roles,
    )


async def test_separate_exact_approval_queue_and_completion_keep_task_open(
    session, test_database_url
) -> None:
    settings = make_test_settings(
        test_database_url,
        COMMUNICATIONS_ENABLED=True,
        GRAPH_SEND_ENABLED=True,
        GRAPH_EXPECTED_MAILBOX_ADDRESS="astralicensing@astraglobal.com",
        COMMUNICATION_REQUIRE_SEPARATE_SEND_APPROVER=True,
        COMMUNICATION_EXTERNAL_RECIPIENT_REQUIRES_MANAGER=False,
    )
    reviewer = actor("reviewer@example.invalid", "Licensing.Reviewer")
    sender = actor("sender@example.invalid", "Licensing.Sender")
    mailbox = await create_mailbox(session)
    email = await create_email(
        session,
        mailbox,
        processing_state="ATTACHMENTS_SAVED",
        sender_email="synthetic-sender@example.invalid",
        subject="Colorado licensing information request",
        body_text="Please provide the current licensing telephone number.",
    )
    await session.commit()
    classification = await ClassificationOrchestrator(session, settings).classify_email(email.id)
    review = await session.scalar(
        select(ClassificationReview).where(
            ClassificationReview.classification_id == classification.id
        )
    )
    review.decision = "APPROVED"
    await session.commit()
    task = await TaskCreationService(session).create(review.id, reviewer)
    task.status = "WAITING_FOR_INFO"
    task.assigned_to = "licensing-owner@example.invalid"
    task.destination_folder_id = "destination-08"
    task.destination_folder_name = "08_Info_Required"
    await session.commit()

    await ResponseTemplateService(session).ensure_defaults()
    template = await session.scalar(
        select(ResponseTemplate).where(ResponseTemplate.template_key == "information-request-ack")
    )
    version = await session.scalar(
        select(ResponseTemplateVersion).where(
            ResponseTemplateVersion.response_template_id == template.id,
            ResponseTemplateVersion.status == "ACTIVE",
        )
    )
    plan = await ResponsePlanService(session).create(
        task.id,
        response_type="ACKNOWLEDGEMENT",
        recipient_mode="REPLY",
        template_version_id=version.id,
        actor=reviewer,
    )
    draft = await DraftGenerationService(session).generate(
        plan.id,
        values={},
        actor=reviewer,
    )
    draft.graph_draft_message_id = "immutable-draft-id"
    draft.graph_change_key = "change-key-1"
    draft.graph_etag = 'W/"etag-1"'
    draft.to_recipients = [{"address": "synthetic-sender@example.invalid", "name": ""}]
    draft.draft_status = CommunicationDraftStatus.GRAPH_DRAFT_CREATED
    await create_version(
        session,
        draft,
        actor_id=reviewer.actor_id,
        change_reason="Graph-generated recipient imported",
    )
    await session.commit()
    await DraftReviewService(session, settings).submit(
        draft.id,
        reviewer,
        expected_revision=draft.local_revision,
        expected_graph_change_key=draft.graph_change_key,
        expected_graph_etag=draft.graph_etag,
    )
    snapshot = approval_snapshot_hash(
        subject=draft.subject,
        body_sha256=draft.body_sha256,
        recipient_sha256=draft.recipient_set_sha256,
        attachment_sha256=draft.attachment_set_sha256,
        revision=draft.local_revision,
        graph_draft_message_id=draft.graph_draft_message_id,
        graph_change_key=draft.graph_change_key,
        graph_etag=draft.graph_etag,
        response_plan_id=str(plan.id),
        template_version_id=str(version.id),
    )
    try:
        await SendApprovalService(session, settings).approve(
            draft.id,
            expected_revision=draft.local_revision,
            expected_snapshot_sha256=snapshot,
            expected_graph_draft_id=draft.graph_draft_message_id,
            expected_graph_change_key=draft.graph_change_key,
            expected_graph_etag=draft.graph_etag,
            notes=None,
            actor=reviewer,
        )
    except Exception as exc:
        assert "cannot approve" in str(exc)
    else:
        raise AssertionError("Draft author unexpectedly approved their own send")
    await SendApprovalService(session, settings).approve(
        draft.id,
        expected_revision=draft.local_revision,
        expected_snapshot_sha256=snapshot,
        expected_graph_draft_id=draft.graph_draft_message_id,
        expected_graph_change_key=draft.graph_change_key,
        expected_graph_etag=draft.graph_etag,
        notes="Exact snapshot reviewed.",
        actor=sender,
    )
    job_id, created = await CommunicationEnqueueService(session, settings).send(
        draft.id,
        idempotency_key="synthetic-send-key",
        explicit_confirmation=True,
        actor=sender,
    )
    duplicate_job_id, duplicate_created = await CommunicationEnqueueService(session, settings).send(
        draft.id,
        idempotency_key="synthetic-send-key",
        explicit_confirmation=True,
        actor=sender,
    )
    assert created and not duplicate_created and duplicate_job_id == job_id
    session.add(
        MailboxFolder(
            mailbox_id=mailbox.id,
            graph_folder_id="sent-items",
            display_name="Sent Items",
            purpose="SENT_ITEMS",
            is_hidden=False,
        )
    )
    await session.commit()

    message_url = (
        "https://graph.microsoft.com/v1.0/users/"
        "astralicensing%40astraglobal.com/messages/immutable-draft-id"
    )
    source_move_url = (
        "https://graph.microsoft.com/v1.0/users/"
        f"astralicensing%40astraglobal.com/messages/{email.graph_message_id}/move"
    )
    graph = GraphHttpClient(settings, FakeTokenProvider())
    with respx.mock:
        respx.get(re.compile(re.escape(message_url) + r"(?:\?.*)?$"), name="immutable_get").mock(
            side_effect=[
                Response(
                    200,
                    json={
                        "id": "immutable-draft-id",
                        "isDraft": True,
                        "subject": draft.subject,
                        "body": {"contentType": "Text", "content": draft.body_text},
                        "toRecipients": [
                            {
                                "emailAddress": {
                                    "address": "synthetic-sender@example.invalid",
                                    "name": "",
                                }
                            }
                        ],
                        "ccRecipients": [],
                        "bccRecipients": [],
                        "changeKey": "change-key-1",
                        "@odata.etag": 'W/"etag-1"',
                        "hasAttachments": False,
                    },
                ),
                Response(
                    200,
                    json={
                        "id": "immutable-draft-id",
                        "isDraft": False,
                        "subject": draft.subject,
                        "body": {"contentType": "Text", "content": draft.body_text},
                        "toRecipients": [
                            {
                                "emailAddress": {
                                    "address": "synthetic-sender@example.invalid",
                                    "name": "",
                                }
                            }
                        ],
                        "ccRecipients": [],
                        "bccRecipients": [],
                        "hasAttachments": False,
                        "parentFolderId": "sent-items",
                        "sentDateTime": "2026-07-22T12:00:00Z",
                        "internetMessageId": "<synthetic@example.invalid>",
                    },
                ),
            ]
        )
        send_route = respx.post(f"{message_url}/send").mock(
            return_value=Response(202, headers={"request-id": "send-request"})
        )
        move_route = respx.post(source_move_url).mock(
            return_value=Response(
                201,
                json={
                    "id": "immutable-moved-source-id",
                    "parentFolderId": "destination-08",
                },
            )
        )
        attempt = await OutboundSendService(session, settings, graph).execute(
            draft.id, job_id=job_id
        )
        assert attempt.status == "ACCEPTED" and send_route.call_count == 1
        attempt = await SentReconciliationService(session, settings, graph).reconcile(draft.id)
        assert attempt.status == "SENT_COPY_VERIFIED"
        settings.graph_message_move_enabled = True
        move = await SourceMoveService(session, settings, graph).execute(email.id)
        assert move.status == MoveAttemptStatus.VERIFIED and move_route.call_count == 1
    await graph.aclose()

    completion = await WorkflowCompletionService(session).complete(email.id, sender)
    await session.refresh(task)
    final_email = await session.get(Email, email.id)
    assert final_email.processing_state == "COMPLETED"
    assert completion.task_status_at_completion == "WAITING_FOR_INFO"
    assert task.status == "WAITING_FOR_INFO"
    assert task.completed_at is None
    assert draft.delivery_status == "UNKNOWN"


async def test_outlook_edit_creates_revision_and_invalidates_exact_approval(
    session, test_database_url
) -> None:
    settings = make_test_settings(test_database_url, COMMUNICATIONS_ENABLED=True)
    reviewer = actor("reviewer@example.invalid", "Licensing.Reviewer")
    mailbox = await create_mailbox(session)
    email = await create_email(
        session,
        mailbox,
        processing_state="ATTACHMENTS_SAVED",
        sender_email="synthetic-sender@example.invalid",
        subject="Synthetic information request",
        body_text="Please acknowledge.",
    )
    await session.commit()
    classification = await ClassificationOrchestrator(session, settings).classify_email(email.id)
    review = await session.scalar(
        select(ClassificationReview).where(
            ClassificationReview.classification_id == classification.id
        )
    )
    review.decision = "APPROVED"
    await session.commit()
    task = await TaskCreationService(session).create(review.id, reviewer)
    task.assigned_to = "licensing-owner@example.invalid"
    task.destination_folder_id = "destination-08"
    task.destination_folder_name = "08_Info_Required"
    await session.commit()
    await ResponseTemplateService(session).ensure_defaults()
    template = await session.scalar(
        select(ResponseTemplate).where(ResponseTemplate.template_key == "information-request-ack")
    )
    template_version = await session.scalar(
        select(ResponseTemplateVersion).where(
            ResponseTemplateVersion.response_template_id == template.id,
            ResponseTemplateVersion.status == "ACTIVE",
        )
    )
    plan = await ResponsePlanService(session).create(
        task.id,
        response_type="ACKNOWLEDGEMENT",
        recipient_mode="REPLY",
        template_version_id=template_version.id,
        actor=reviewer,
    )
    draft = await DraftGenerationService(session).generate(
        plan.id,
        values={},
        actor=reviewer,
    )
    draft.graph_draft_message_id = "immutable-outlook-draft"
    draft.graph_change_key = "change-key-1"
    draft.graph_etag = 'W/"etag-1"'
    draft.to_recipients = [{"address": "synthetic-sender@example.invalid", "name": ""}]
    draft.draft_status = CommunicationDraftStatus.PENDING_SEND_APPROVAL
    version = await create_version(
        session,
        draft,
        actor_id=reviewer.actor_id,
        change_reason="Graph-generated recipient imported",
    )
    approval = SendApproval(
        outbound_draft_id=draft.id,
        draft_version_id=version.id,
        decision="APPROVED",
        approver_actor="sender@example.invalid",
        approval_snapshot_sha256="old-snapshot",
        body_sha256=draft.body_sha256,
        recipient_set_sha256=draft.recipient_set_sha256,
        attachment_set_sha256=draft.attachment_set_sha256,
        graph_draft_message_id=draft.graph_draft_message_id,
        graph_change_key=draft.graph_change_key,
        graph_etag=draft.graph_etag,
    )
    draft.approval_snapshot_sha256 = "old-snapshot"
    session.add(approval)
    await session.commit()
    prior_revision = draft.local_revision

    graph = GraphHttpClient(settings, FakeTokenProvider())
    message_url = (
        "https://graph.microsoft.com/v1.0/users/astralicensing%40astraglobal.com/"
        "messages/immutable-outlook-draft"
    )
    with respx.mock:
        respx.get(re.compile(re.escape(message_url) + r"(?:\?.*)?$")).mock(
            return_value=Response(
                200,
                json={
                    "id": "immutable-outlook-draft",
                    "isDraft": True,
                    "subject": draft.subject,
                    "body": {
                        "contentType": "Text",
                        "content": f"{draft.body_text}\nOutlook-side edit",
                    },
                    "toRecipients": [
                        {
                            "emailAddress": {
                                "address": "synthetic-sender@example.invalid",
                                "name": "",
                            }
                        }
                    ],
                    "ccRecipients": [],
                    "bccRecipients": [],
                    "changeKey": "change-key-2",
                    "@odata.etag": 'W/"etag-2"',
                    "hasAttachments": False,
                },
            )
        )
        observed, changed = await GraphDraftService(session, settings, graph).sync(
            draft.id, reviewer
        )
    await graph.aclose()

    await session.refresh(approval)
    assert changed
    assert observed.local_revision == prior_revision + 1
    assert observed.draft_status == CommunicationDraftStatus.CHANGES_REQUESTED
    assert observed.approval_snapshot_sha256 is None
    assert approval.decision == "INVALIDATED"
    assert approval.invalidation_reason == "external Outlook draft edit"
