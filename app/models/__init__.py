"""ORM models. Importing this package registers every table on Base.metadata."""

from app.db.base import Base
from app.models.classification import Classification
from app.models.draft import OutboundDraft
from app.models.email import Email, EmailAttachment, EmailRecipient
from app.models.event import AuditEvent, EmailProcessingEvent
from app.models.graph_subscription import GraphSubscription
from app.models.heartbeat import WorkerHeartbeat
from app.models.job import GraphJob
from app.models.mailbox import Mailbox, MailboxFolder, MailboxSyncState
from app.models.notification import GraphNotificationReceipt
from app.models.outbox import OutboxEvent
from app.models.review import ClassificationReview
from app.models.task import LicensingTask, TaskRequestedItem

__all__ = [
    "AuditEvent",
    "Base",
    "Classification",
    "ClassificationReview",
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
    "OutboundDraft",
    "OutboxEvent",
    "TaskRequestedItem",
    "WorkerHeartbeat",
]
