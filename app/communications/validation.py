"""Draft content validation independent of transport."""

from __future__ import annotations

import re

from app.communications.rendering import PLACEHOLDER

UNSAFE_HTML = re.compile(
    r"<\s*(script|iframe|object|embed|form|input|style|link|meta)\b"
    r"|\b(?:on[a-z]+|style)\s*="
    r"|\b(?:href|src|action|formaction)\s*=\s*['\"]?\s*(?:javascript|data)\s*:",
    re.IGNORECASE,
)


def validate_draft_content(
    *, subject: str, body_text: str | None, body_html: str | None, attachment_count: int
) -> list[str]:
    findings: list[str] = []
    combined = "\n".join((subject, body_text or "", body_html or ""))
    if not subject.strip() or not (body_text or body_html):
        findings.append("DRAFT_CONTENT_MISSING")
    if PLACEHOLDER.search(combined):
        findings.append("UNRESOLVED_PLACEHOLDER")
    if body_html and UNSAFE_HTML.search(body_html):
        findings.append("UNSAFE_HTML")
    says_attached = bool(re.search(r"\b(attached|attachment|enclosed)\b", combined, re.I))
    if says_attached and attachment_count == 0:
        findings.append("ATTACHMENT_REFERENCE_WITHOUT_ATTACHMENT")
    return findings
