"""Deterministic-first classifier with traceable evidence and conservative extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parseaddr

from app.classification.preprocessing import CleanBody, normalize_body
from app.classification.schema import (
    ClassificationDocumentV1,
    ClassificationOutputV1,
    RequestedInformationV1,
)
from app.classification.taxonomy import DESTINATIONS, LICENSE_PHRASES, US_STATES


@dataclass(frozen=True)
class AttachmentSignal:
    filename: str
    mime_type: str | None = None
    document_type: str = "UNCLASSIFIED"


@dataclass(frozen=True)
class ClassificationInput:
    subject: str
    body: str
    sender_email: str | None = None
    reply_to: str | None = None
    attachments: tuple[AttachmentSignal, ...] = ()
    received_date: date | None = None


@dataclass(frozen=True)
class VendorSignal:
    canonical_name: str
    domains: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    trust_level: str = "VERIFIED"


@dataclass(frozen=True)
class RuleEvidence:
    rule_id: str
    rule_version: int
    source_field: str
    matched_text: str
    normalized_value: str
    score_contribution: float


@dataclass(frozen=True)
class DeterministicResult:
    output: ClassificationOutputV1
    evidence: tuple[RuleEvidence, ...]
    clean_body: CleanBody


class DeterministicClassifier:
    def __init__(self, vendors: tuple[VendorSignal, ...] = ()) -> None:
        self.vendors = vendors or (
            VendorSignal("RASI", ("rasi.com", "rasi.biz")),
            VendorSignal(
                "NMLS", ("nmlsconsumeraccess.org", "mortgage.nationwidelicensingsystem.org")
            ),
        )

    def classify(self, value: ClassificationInput) -> DeterministicResult:
        clean = normalize_body(value.body)
        subject, body = value.subject or "", clean.current_message
        joined = f"{subject}\n{body}"
        lower = joined.casefold()
        evidence: list[RuleEvidence] = []
        vendor = self._vendor(value.sender_email, evidence)
        states = self._states(joined, evidence)
        licenses = self._licenses(lower, evidence)
        numbers = self._license_numbers(joined, evidence)
        requests = self._requests(body, evidence)
        email_type = self._email_type(lower, bool(requests), evidence)
        due_date = self._due_date(body, value.received_date, evidence)
        destination = self._route(email_type, vendor)
        documents = [
            ClassificationDocumentV1(
                filename=a.filename,
                document_type=a.document_type,
                relationship="supporting_document",
            )
            for a in value.attachments
        ]
        confidence = min(0.99, round(0.35 + sum(item.score_contribution for item in evidence), 2))
        review_reasons = ["Initial rollout requires review."]
        if confidence < 0.9:
            review_reasons.append("Classification confidence is below the review threshold.")
        action_required = bool(requests) or email_type in {
            "missing_information_request",
            "renewal_notice",
            "bond_correspondence",
            "invoice_or_fee",
        }
        state_label = ", ".join(states) or "Unspecified jurisdiction"
        summary = f"{vendor or 'Unknown sender'} {email_type.replace('_', ' ')} for {state_label}."
        output = ClassificationOutputV1(
            vendor=vendor,
            email_type=email_type,
            states=states,
            license_types=licenses,
            license_numbers=numbers,
            action_required=action_required,
            requested_information=requests,
            documents=documents,
            due_date=due_date,
            summary=summary,
            proposed_action="Review the evidence and complete the requested licensing work."
            if action_required
            else "Review and file the correspondence.",
            suggested_destination=destination,
            confidence=confidence,
            requires_human_review=True,
            review_reasons=review_reasons,
        )
        return DeterministicResult(output=output, evidence=tuple(evidence), clean_body=clean)

    def _vendor(self, sender: str | None, evidence: list[RuleEvidence]) -> str | None:
        address = parseaddr(sender or "")[1].casefold()
        domain = address.rpartition("@")[2]
        for vendor in self.vendors:
            if address in {v.casefold() for v in vendor.addresses} or any(
                domain == d or domain.endswith("." + d) for d in vendor.domains
            ):
                evidence.append(
                    RuleEvidence("vendor.sender", 1, "sender", address, vendor.canonical_name, 0.25)
                )
                return vendor.canonical_name
        return None

    def _states(self, text: str, evidence: list[RuleEvidence]) -> list[str]:
        found: list[str] = []
        for abbr, name in US_STATES.items():
            match = re.search(rf"\b(?:{re.escape(name)}|{abbr})\b", text, re.I)
            if match and name not in found:
                found.append(name)
                evidence.append(
                    RuleEvidence("state.canonical", 1, "subject_or_body", match.group(), name, 0.08)
                )
        return found

    def _licenses(self, lower: str, evidence: list[RuleEvidence]) -> list[str]:
        found = []
        for phrase, canonical in LICENSE_PHRASES.items():
            if phrase in lower:
                found.append(canonical)
                evidence.append(
                    RuleEvidence("license.phrase", 1, "subject_or_body", phrase, canonical, 0.08)
                )
        return found

    def _license_numbers(self, text: str, evidence: list[RuleEvidence]) -> list[str]:
        pattern = re.compile(
            r"(?i)\b(?:license|lic\.?|number|no\.?)\s*(?:#|number|no\.)?\s*[:#-]?\s*"
            r"([A-Z]{0,4}[- ]?[A-Z0-9]{3,15})\b"
        )
        values = []
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if any(ch.isdigit() for ch in candidate) and candidate not in values:
                values.append(candidate)
                evidence.append(
                    RuleEvidence(
                        "license.number", 1, "subject_or_body", match.group(), candidate, 0.08
                    )
                )
        return values

    def _requests(self, body: str, evidence: list[RuleEvidence]) -> list[RequestedInformationV1]:
        items: list[RequestedInformationV1] = []
        intro = re.compile(
            r"(?i)^(please provide|requested information|information required)\s*:?[\s]*$"
        )
        deadline = re.compile(r"(?i)\b(due|deadline|by)\b.*\b\d{1,2}\b")
        for raw in body.splitlines():
            line = raw.strip(" \t-*•")
            if (
                len(line) < 4
                or intro.match(line)
                or deadline.search(line)
                or line.casefold() in {"thank you", "thanks", "sincerely", "regards"}
            ):
                continue
            explicit = re.match(
                r"(?i)^(?:please\s+)?(?:provide|submit|send|confirm|complete|upload)\s+(.+?)[.!]?$",
                line,
            )
            bullet = raw.lstrip().startswith(("-", "*", "•")) and len(line.split()) >= 2
            if not explicit and not bullet:
                continue
            item = (explicit.group(1) if explicit else line).strip().rstrip(".")
            category = (
                "contact_information"
                if re.search(r"(?i)phone|telephone|address|email", item)
                else "supporting_document"
                if re.search(r"(?i)document|certificate|statement|report|copy", item)
                else "unknown"
            )
            quote = line[:1000]
            items.append(
                RequestedInformationV1(
                    item=item[:500], category=category, required=True, evidence_quote=quote
                )
            )
            evidence.append(
                RuleEvidence("request.explicit", 1, "current_message_body", quote, item, 0.12)
            )
        return items

    def _email_type(self, lower: str, has_requests: bool, evidence: list[RuleEvidence]) -> str:
        rules = [
            (
                "missing_information_request",
                has_requests or "information required" in lower or "missing information" in lower,
                0.14,
            ),
            ("bond_correspondence", "bond" in lower, 0.10),
            ("invoice_or_fee", "invoice" in lower or "fee due" in lower, 0.10),
            (
                "submission_confirmation",
                "submission confirmation" in lower or "successfully submitted" in lower,
                0.10,
            ),
            (
                "license_or_proof_received",
                "license attached" in lower or "certificate attached" in lower,
                0.10,
            ),
            ("renewal_notice", "renewal" in lower, 0.08),
            ("regulator_correspondence", "regulator" in lower, 0.06),
        ]
        for kind, matched, score in rules:
            if matched:
                evidence.append(
                    RuleEvidence(
                        f"type.{kind}", 1, "subject_or_body", kind.replace("_", " "), kind, score
                    )
                )
                return kind
        return "general_correspondence"

    def _due_date(
        self, body: str, received: date | None, evidence: list[RuleEvidence]
    ) -> date | None:
        iso = re.search(r"(?i)\b(?:due|deadline|by)\s*(?:on\s*)?(20\d{2}-\d{2}-\d{2})\b", body)
        if iso:
            value = date.fromisoformat(iso.group(1))
            evidence.append(
                RuleEvidence(
                    "date.iso", 1, "current_message_body", iso.group(), value.isoformat(), 0.1
                )
            )
            return value
        named = re.search(
            r"(?i)\b(?:due|deadline|by)\s*(?:on\s*)?([A-Z][a-z]+)\s+(\d{1,2})(?:,\s*(20\d{2}))?",
            body,
        )
        if named:
            year = int(named.group(3) or (received.year if received else datetime.now().year))
            try:
                value = datetime.strptime(
                    f"{named.group(1)} {named.group(2)} {year}", "%B %d %Y"
                ).date()
            except ValueError:
                return None
            evidence.append(
                RuleEvidence(
                    "date.named", 1, "current_message_body", named.group(), value.isoformat(), 0.1
                )
            )
            return value
        return None

    @staticmethod
    def _route(email_type: str, vendor: str | None) -> str:
        if vendor == "NMLS":
            return "04_NMLS"
        if vendor == "RASI" and email_type == "renewal_notice":
            return "02_RASI"
        return DESTINATIONS.get(email_type, "09_Internal_Followups")
