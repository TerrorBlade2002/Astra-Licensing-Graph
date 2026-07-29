"""ORM models. Importing this package registers every table on Base.metadata."""

from app.db.base import Base
from app.models.classification import Classification
from app.models.communication import (
    CommunicationJob,
    MessageMoveAttempt,
    OutboundSendAttempt,
    RecipientPolicyRule,
    ResponsePlan,
    ResponseTemplate,
    ResponseTemplateVersion,
    SendApproval,
    WorkflowCompletionRecord,
)
from app.models.document import (
    Document,
    DocumentJob,
    DocumentLink,
    DocumentMetadataEvent,
    DocumentVersion,
)
from app.models.draft import OutboundDraft, OutboundDraftAttachment, OutboundDraftVersion
from app.models.email import Email, EmailAttachment, EmailRecipient
from app.models.event import AuditEvent, EmailProcessingEvent
from app.models.graph_subscription import GraphSubscription
from app.models.heartbeat import WorkerHeartbeat
from app.models.job import GraphJob
from app.models.mailbox import Mailbox, MailboxFolder, MailboxSyncState
from app.models.milestone4 import (
    ClassificationFieldCorrection,
    ClassificationRule,
    ClassificationRuleSet,
    ClassificationRun,
    Organization,
    OrganizationAddress,
    OrganizationDomain,
    PromptVersion,
    UserPreference,
    UserPrincipal,
    UserRoleSnapshot,
)
from app.models.notification import GraphNotificationReceipt
from app.models.outbox import OutboxEvent
from app.models.review import ClassificationReview
from app.models.sharepoint import (
    SharePointDrive,
    SharePointFolder,
    SharePointSite,
    SharePointSyncState,
    SharePointUploadSession,
)
from app.models.task import LicensingTask, TaskComment, TaskEvent, TaskRequestedItem

__all__ = [
    "AuditEvent",
    "Base",
    "Classification",
    "ClassificationFieldCorrection",
    "ClassificationReview",
    "ClassificationRule",
    "ClassificationRuleSet",
    "ClassificationRun",
    "CommunicationJob",
    "Document",
    "DocumentJob",
    "DocumentLink",
    "DocumentMetadataEvent",
    "DocumentVersion",
    "Email",
    "EmailAttachment",
    "EmailProcessingEvent",
    "EmailRecipient",
    "GraphJob",
    "GraphNotificationReceipt",
    "GraphSubscription",
    "LicensingTask",
    "Mailbox",
    "MailboxFolder",
    "MailboxSyncState",
    "MessageMoveAttempt",
    "Organization",
    "OrganizationAddress",
    "OrganizationDomain",
    "OutboundDraft",
    "OutboundDraftAttachment",
    "OutboundDraftVersion",
    "OutboundSendAttempt",
    "OutboxEvent",
    "PromptVersion",
    "RecipientPolicyRule",
    "ResponsePlan",
    "ResponseTemplate",
    "ResponseTemplateVersion",
    "SendApproval",
    "SharePointDrive",
    "SharePointFolder",
    "SharePointSite",
    "SharePointSyncState",
    "SharePointUploadSession",
    "TaskComment",
    "TaskEvent",
    "TaskRequestedItem",
    "UserPreference",
    "UserPrincipal",
    "UserRoleSnapshot",
    "WorkerHeartbeat",
    "WorkflowCompletionRecord",
]
