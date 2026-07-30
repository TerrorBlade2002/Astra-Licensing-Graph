"""Fail-closed adapter contract for human-supervised portal assistance."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageIdentity:
    category: str
    fingerprint: str
    safe_url_path: str


@dataclass(frozen=True)
class SubmissionResult:
    outcome: str
    page_category: str
    confirmation_reference: str | None = None
    ambiguous: bool = False


class PortalAdapter(ABC):
    adapter_key: str
    supported_filing_types: frozenset[str]
    allowed_actions: frozenset[str]
    prohibited_actions: frozenset[str]
    required_handoffs: frozenset[str]

    def __init__(self, *, locator_contract: dict[str, Any], contract_version: str) -> None:
        self.locator_contract = locator_contract
        self.contract_version = contract_version

    @abstractmethod
    async def detect_login_state(self, page: Any) -> str: ...

    @abstractmethod
    async def begin_login_handoff(self, page: Any) -> PageIdentity: ...

    @abstractmethod
    async def navigate_to_filing(self, page: Any, route: dict[str, Any]) -> PageIdentity: ...

    @abstractmethod
    async def identify_current_page(self, page: Any) -> PageIdentity | None: ...

    @abstractmethod
    async def collect_page_contract(self, page: Any) -> dict[str, Any]: ...

    @abstractmethod
    async def enter_field(self, page: Any, field_key: str, value: str) -> None: ...

    @abstractmethod
    async def read_field(self, page: Any, field_key: str) -> str: ...

    @abstractmethod
    async def list_validation_messages(self, page: Any) -> list[dict[str, str]]: ...

    @abstractmethod
    async def upload_document(self, page: Any, category: str, path: str) -> None: ...

    @abstractmethod
    async def verify_uploaded_document(
        self, page: Any, *, filename: str, size_bytes: int
    ) -> bool: ...

    @abstractmethod
    async def save_draft(self, page: Any) -> PageIdentity: ...

    @abstractmethod
    async def capture_pre_submission_state(self, page: Any) -> dict[str, Any]: ...

    @abstractmethod
    async def detect_attestation_step(self, page: Any) -> bool: ...

    @abstractmethod
    async def read_attestation_fingerprint(self, page: Any) -> str | None: ...

    @abstractmethod
    async def detect_payment_step(self, page: Any) -> bool: ...

    @abstractmethod
    async def read_payment_summary(self, page: Any) -> dict[str, str]: ...

    @abstractmethod
    async def detect_final_submit_step(self, page: Any) -> bool: ...

    @abstractmethod
    async def detect_submission_result(self, page: Any) -> SubmissionResult: ...

    @abstractmethod
    async def capture_confirmation(self, page: Any) -> dict[str, Any]: ...

    @abstractmethod
    async def close_session(self, page: Any) -> None: ...
