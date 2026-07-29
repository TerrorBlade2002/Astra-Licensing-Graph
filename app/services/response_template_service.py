"""Immutable, versioned deterministic response templates."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actors import CurrentActor
from app.communications.audit import add_communication_audit
from app.communications.hashes import canonical_sha256
from app.communications.rendering import ResponseTemplateRenderer
from app.communications.validation import UNSAFE_HTML
from app.core.exceptions import NotFoundError
from app.models import ResponseTemplate, ResponseTemplateVersion
from app.models.mixins import utcnow

DEFAULT_VARIABLES = [
    "vendor_name",
    "jurisdiction",
    "license_type",
    "license_number",
    "requested_items",
    "due_date",
    "task_owner_name",
    "licensing_mailbox",
    "approved_document_list",
    "legal_entity",
    "response_reference",
]

DEFAULT_TEMPLATES = {
    "information-request-ack": (
        "Acknowledgement of information request",
        "ACKNOWLEDGEMENT",
        "Re: {{ response_reference }}",
        "We acknowledge receipt of the information request from {{ vendor_name }}. "
        "The request is under review; this acknowledgement does not represent that the "
        "requested information has been supplied.",
    ),
    "information-response": (
        "Approved information response",
        "INFORMATION_RESPONSE",
        "Re: {{ response_reference }}",
        "Please find the verified requested information for {{ jurisdiction }} below:\n"
        "{{ requested_items }}",
    ),
    "bond-ack": (
        "Bond correspondence acknowledgement",
        "BOND_RESPONSE",
        "Re: {{ response_reference }}",
        "We acknowledge receipt of the bond correspondence and are reviewing it.",
    ),
    "regulator-ack": (
        "Regulator correspondence acknowledgement",
        "REGULATOR_RESPONSE",
        "Re: {{ response_reference }}",
        "We acknowledge receipt of the regulator correspondence and are reviewing it.",
    ),
    "fee-review-ack": (
        "Invoice or fee review acknowledgement",
        "PAYMENT_CONFIRMATION",
        "Re: {{ response_reference }}",
        "We acknowledge receipt of the fee notice. It is under review; payment is not confirmed.",
    ),
    "submission-ack": (
        "Submission confirmation acknowledgement",
        "FILING_CONFIRMATION",
        "Re: {{ response_reference }}",
        "We acknowledge receipt of the submission confirmation and are reviewing the record.",
    ),
    "document-response": (
        "Approved controlled-document response",
        "DOCUMENT_RESPONSE",
        "Re: {{ response_reference }}",
        "Please review the approved controlled documents provided with this response. "
        "Only the document versions displayed in the approved attachment set are authorized.",
    ),
    "clarification-response": (
        "Licensing clarification response",
        "CLARIFICATION_RESPONSE",
        "Re: {{ response_reference }}",
        "This response provides the reviewed clarification requested by {{ vendor_name }}.",
    ),
    "internal-forward": (
        "Controlled internal forward",
        "INTERNAL_FORWARD",
        "Fwd: {{ response_reference }}",
        "Forwarded for internal licensing review. No external response has been authorized.",
    ),
}


class ResponseTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_version(
        self,
        template_id: uuid.UUID,
        *,
        subject: str | None,
        body: str,
        html_body: str | None,
        allowed_variables: list[str],
        actor: CurrentActor,
    ) -> ResponseTemplateVersion:
        template = await self.session.get(ResponseTemplate, template_id)
        if template is None:
            raise NotFoundError("Response template does not exist.")
        unsupported = set(allowed_variables) - set(DEFAULT_VARIABLES)
        if unsupported:
            raise ValueError(f"Template variables are not approved: {sorted(unsupported)}")
        ResponseTemplateRenderer().validate_template(subject or "", allowed_variables)
        ResponseTemplateRenderer().validate_template(body, allowed_variables)
        ResponseTemplateRenderer().validate_template(html_body or "", allowed_variables)
        if html_body and UNSAFE_HTML.search(html_body):
            raise ValueError("Template HTML contains unsafe markup.")
        latest = await self.session.scalar(
            select(func.max(ResponseTemplateVersion.version)).where(
                ResponseTemplateVersion.response_template_id == template_id
            )
        )
        row = ResponseTemplateVersion(
            response_template_id=template_id,
            version=int(latest or 0) + 1,
            status="DRAFT",
            subject_template=subject,
            text_body_template=body,
            html_body_template=html_body,
            allowed_variables=allowed_variables,
            validation_rules={},
            template_sha256=canonical_sha256(
                {
                    "subject": subject,
                    "body": body,
                    "html_body": html_body,
                    "allowed_variables": allowed_variables,
                }
            ),
            created_by_actor=actor.actor_id,
        )
        self.session.add(row)
        await self.session.flush()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="response_template_version",
            entity_id=row.id,
            action="template_version_created",
            after={"version": row.version, "status": row.status},
        )
        await self.session.commit()
        return row

    async def activate(self, version_id: uuid.UUID, actor: CurrentActor) -> ResponseTemplateVersion:
        row = await self.session.get(ResponseTemplateVersion, version_id)
        if row is None or row.status != "DRAFT":
            raise ValueError("Only a draft template version can be activated.")
        expected_hash = canonical_sha256(
            {
                "subject": row.subject_template,
                "body": row.text_body_template,
                "html_body": row.html_body_template,
                "allowed_variables": row.allowed_variables,
            }
        )
        if expected_hash != row.template_sha256:
            raise ValueError("Template version changed after its immutable hash was recorded.")
        unsupported = set(row.allowed_variables) - set(DEFAULT_VARIABLES)
        if unsupported:
            raise ValueError(f"Template variables are not approved: {sorted(unsupported)}")
        ResponseTemplateRenderer().validate_template(
            row.subject_template or "", row.allowed_variables
        )
        ResponseTemplateRenderer().validate_template(row.text_body_template, row.allowed_variables)
        ResponseTemplateRenderer().validate_template(
            row.html_body_template or "", row.allowed_variables
        )
        if row.html_body_template and UNSAFE_HTML.search(row.html_body_template):
            raise ValueError("Template HTML contains unsafe markup.")
        current = list(
            await self.session.scalars(
                select(ResponseTemplateVersion).where(
                    ResponseTemplateVersion.response_template_id == row.response_template_id,
                    ResponseTemplateVersion.status == "ACTIVE",
                )
            )
        )
        for previous in current:
            previous.status = "RETIRED"
        row.status = "ACTIVE"
        row.approved_by_actor = actor.actor_id
        row.activated_at = utcnow()
        add_communication_audit(
            self.session,
            actor=actor,
            entity_type="response_template_version",
            entity_id=row.id,
            action="template_version_activated",
            before={"status": "DRAFT"},
            after={"status": "ACTIVE", "version": row.version},
        )
        await self.session.commit()
        return row

    async def ensure_defaults(self, actor_id: str = "system") -> None:
        for key, (name, response_type, subject, body) in DEFAULT_TEMPLATES.items():
            existing = await self.session.scalar(
                select(ResponseTemplate).where(ResponseTemplate.template_key == key)
            )
            if existing:
                continue
            template = ResponseTemplate(
                template_key=key, name=name, response_type=response_type, is_active=True
            )
            self.session.add(template)
            await self.session.flush()
            self.session.add(
                ResponseTemplateVersion(
                    response_template_id=template.id,
                    version=1,
                    status="ACTIVE",
                    subject_template=subject,
                    text_body_template=body,
                    allowed_variables=DEFAULT_VARIABLES,
                    validation_rules={},
                    template_sha256=canonical_sha256(
                        {"subject": subject, "body": body, "allowed_variables": DEFAULT_VARIABLES}
                    ),
                    created_by_actor=actor_id,
                    approved_by_actor=actor_id,
                    activated_at=utcnow(),
                )
            )
        await self.session.commit()
