"""Official-API adapter boundary.

Only draft preparation, approved uploads, and validation are represented. There
is deliberately no submit, attestation, payment, signature, or terms method.
Authentication is injected at runtime from an approved secrets manager or
delegated token provider; tokens are never accepted from database records.
"""

from __future__ import annotations

from typing import Protocol


class OfficialApiTransport(Protocol):
    async def put_reviewed_field(
        self, *, route_key: str, field_key: str, value: str
    ) -> dict[str, object]: ...

    async def upload_reviewed_document(
        self,
        *,
        route_key: str,
        category: str,
        filename: str,
        content: bytes,
        sha256: str,
    ) -> dict[str, object]: ...

    async def read_draft(self, *, route_key: str) -> dict[str, object]: ...

    async def validate_draft(self, *, route_key: str) -> list[dict[str, object]]: ...


class OfficialApiAssistedAdapter:
    """API-first assistance with an intentionally non-submitting contract."""

    adapter_key = "official-api-assisted"
    prohibited_actions = frozenset(
        {
            "ACCEPT_TERMS",
            "ENTER_MFA",
            "SOLVE_CAPTCHA",
            "ATTEST",
            "SIGN",
            "ENTER_PAYMENT_CREDENTIALS",
            "AUTHORIZE_PAYMENT",
            "FINAL_SUBMIT",
        }
    )

    def __init__(self, transport: OfficialApiTransport) -> None:
        self.transport = transport

    async def enter_field(self, *, route_key: str, field_key: str, value: str) -> dict[str, object]:
        return await self.transport.put_reviewed_field(
            route_key=route_key, field_key=field_key, value=value
        )

    async def upload_document(
        self,
        *,
        route_key: str,
        category: str,
        filename: str,
        content: bytes,
        sha256: str,
    ) -> dict[str, object]:
        return await self.transport.upload_reviewed_document(
            route_key=route_key,
            category=category,
            filename=filename,
            content=content,
            sha256=sha256,
        )

    async def compare_and_validate(
        self, *, route_key: str
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        draft = await self.transport.read_draft(route_key=route_key)
        messages = await self.transport.validate_draft(route_key=route_key)
        return draft, messages
