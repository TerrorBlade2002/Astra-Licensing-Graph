"""Contract-driven adapter used only after portal-specific review."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.browser.actions import fill_reviewed_field, upload_reviewed_file
from app.browser.locators import require_unique, resolve_locator
from app.browser.redaction import sanitize_dom
from app.core.crypto import content_sha256
from app.core.exceptions import StateConflictError
from app.portals.adapters.base import PageIdentity, PortalAdapter, SubmissionResult


class GenericAssistedAdapter(PortalAdapter):
    adapter_key = "generic-assisted"
    supported_filing_types = frozenset()
    allowed_actions = frozenset(
        {"NAVIGATE", "ENTER_FIELD", "UPLOAD_DOCUMENT", "SAVE_DRAFT", "VALIDATE"}
    )
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
    required_handoffs = frozenset(
        {"LOGIN", "TERMS_ACCEPTANCE", "MFA", "CAPTCHA", "ATTESTATION", "PAYMENT", "FINAL_SUBMIT"}
    )

    def _page_contract(self, category: str) -> dict[str, Any]:
        value = self.locator_contract.get(category)
        if not isinstance(value, dict):
            raise StateConflictError(f"No reviewed contract for page {category!r}.")
        return value

    async def identify_current_page(self, page: Any) -> PageIdentity | None:
        matches: list[PageIdentity] = []
        for category, contract in self.locator_contract.items():
            if not isinstance(contract, dict):
                continue
            fingerprint = contract.get("fingerprint")
            if not isinstance(fingerprint, dict):
                continue
            locator = resolve_locator(page, fingerprint)
            if await locator.count() == 1:
                matches.append(
                    PageIdentity(
                        category=category,
                        fingerprint=str(contract.get("page_fingerprint", category)),
                        safe_url_path=urlparse(page.url).path[:500],
                    )
                )
        if len(matches) != 1:
            return None
        return matches[0]

    async def detect_login_state(self, page: Any) -> str:
        identity = await self.identify_current_page(page)
        if identity is None:
            return "UNKNOWN"
        return "LOGIN_REQUIRED" if identity.category == "login" else "AUTHENTICATED"

    async def begin_login_handoff(self, page: Any) -> PageIdentity:
        identity = await self.identify_current_page(page)
        if identity is None or identity.category != "login":
            raise StateConflictError("Expected reviewed login page was not found.")
        return identity

    async def navigate_to_filing(self, page: Any, route: dict[str, Any]) -> PageIdentity:
        target = route.get("url")
        if not isinstance(target, str):
            raise StateConflictError("Reviewed filing route has no URL.")
        await page.goto(target, wait_until="domcontentloaded")
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Portal returned an unknown or redesigned page.")
        return identity

    async def collect_page_contract(self, page: Any) -> dict[str, Any]:
        identity = await self.identify_current_page(page)
        if identity is None:
            sanitized = sanitize_dom(await page.content())
            return {
                "category": "UNKNOWN",
                "sanitized_dom_sha256": content_sha256(sanitized),
                "sanitized_dom_size": len(sanitized),
            }
        return {
            "category": identity.category,
            "fingerprint": identity.fingerprint,
            "safe_url_path": identity.safe_url_path,
        }

    async def enter_field(self, page: Any, field_key: str, value: str) -> None:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot enter data on an unknown page.")
        contract = self._page_contract(identity.category).get("locators", {}).get(field_key)
        if not isinstance(contract, dict):
            raise StateConflictError(f"Field {field_key!r} is absent from the reviewed contract.")
        await fill_reviewed_field(
            page, action_key=f"field:{field_key}", locator_contract=contract, value=value
        )

    async def read_field(self, page: Any, field_key: str) -> str:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot read data from an unknown page.")
        contract = self._page_contract(identity.category).get("locators", {}).get(field_key)
        if not isinstance(contract, dict):
            raise StateConflictError(f"Field {field_key!r} is absent from the reviewed contract.")
        locator = await require_unique(resolve_locator(page, contract), contract_key=field_key)
        return str(await locator.input_value())

    async def list_validation_messages(self, page: Any) -> list[dict[str, str]]:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot validate an unknown page.")
        contract = self._page_contract(identity.category).get("validation_locator")
        if not isinstance(contract, dict):
            return []
        locator = resolve_locator(page, contract)
        return [
            {"category": identity.category, "message": text[:1000]}
            for text in await locator.all_inner_texts()
        ]

    async def upload_document(self, page: Any, category: str, path: str) -> None:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot upload on an unknown page.")
        contract = self._page_contract(identity.category).get("upload_locators", {}).get(category)
        if not isinstance(contract, dict):
            raise StateConflictError(f"Upload category {category!r} is not reviewed.")
        await upload_reviewed_file(
            page,
            action_key=f"upload:{category}",
            locator_contract=contract,
            file_path=path,
        )

    async def verify_uploaded_document(self, page: Any, *, filename: str, size_bytes: int) -> bool:
        identity = await self.identify_current_page(page)
        if identity is None:
            return False
        contract = self._page_contract(identity.category).get("uploaded_file_locator")
        if not isinstance(contract, dict):
            return False
        locator = resolve_locator(page, contract)
        texts = await locator.all_inner_texts()
        return any(filename in text and str(size_bytes) in text for text in texts)

    async def save_draft(self, page: Any) -> PageIdentity:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot save an unknown page.")
        contract = self._page_contract(identity.category).get("locators", {}).get("save_draft")
        if not isinstance(contract, dict):
            raise StateConflictError("Reviewed page has no save-draft action.")
        locator = await require_unique(resolve_locator(page, contract), contract_key="save_draft")
        await locator.click()
        result = await self.identify_current_page(page)
        if result is None:
            raise StateConflictError("Portal changed after save-draft.")
        return result

    async def capture_pre_submission_state(self, page: Any) -> dict[str, Any]:
        identity = await self.identify_current_page(page)
        if identity is None:
            raise StateConflictError("Cannot capture an unknown page.")
        return await self.collect_page_contract(page)

    async def _is_category(self, page: Any, category: str) -> bool:
        identity = await self.identify_current_page(page)
        return bool(identity and identity.category == category)

    async def detect_attestation_step(self, page: Any) -> bool:
        return await self._is_category(page, "attestation")

    async def read_attestation_fingerprint(self, page: Any) -> str | None:
        identity = await self.identify_current_page(page)
        if identity is None or identity.category != "attestation":
            raise StateConflictError("A reviewed attestation page is not present.")
        contract = self._page_contract("attestation").get("attestation_text_locator")
        if not isinstance(contract, dict):
            return None
        locator = await require_unique(
            resolve_locator(page, contract), contract_key="attestation_text_locator"
        )
        text = " ".join((await locator.inner_text()).split())
        return content_sha256(text)

    async def detect_payment_step(self, page: Any) -> bool:
        return await self._is_category(page, "payment")

    async def read_payment_summary(self, page: Any) -> dict[str, str]:
        identity = await self.identify_current_page(page)
        if identity is None or identity.category != "payment":
            raise StateConflictError("A reviewed payment page is not present.")
        page_contract = self._page_contract("payment")
        summary: dict[str, str] = {}
        for output_key, contract_key in (
            ("displayed_fee", "fee_amount_locator"),
            ("currency", "currency_locator"),
        ):
            contract = page_contract.get(contract_key)
            if isinstance(contract, dict):
                locator = await require_unique(
                    resolve_locator(page, contract), contract_key=contract_key
                )
                summary[output_key] = (await locator.inner_text())[:120]
        return summary

    async def detect_final_submit_step(self, page: Any) -> bool:
        return await self._is_category(page, "final_submit")

    async def detect_submission_result(self, page: Any) -> SubmissionResult:
        identity = await self.identify_current_page(page)
        if identity is None:
            return SubmissionResult("UNKNOWN", "UNKNOWN", ambiguous=True)
        if identity.category == "confirmation":
            return SubmissionResult("CONFIRMED", identity.category)
        if identity.category == "submission_error":
            return SubmissionResult("FAILED", identity.category)
        return SubmissionResult("PENDING", identity.category, ambiguous=True)

    async def capture_confirmation(self, page: Any) -> dict[str, Any]:
        identity = await self.identify_current_page(page)
        if identity is None or identity.category != "confirmation":
            raise StateConflictError("A reviewed confirmation page is not present.")
        contract = self._page_contract("confirmation").get("confirmation_locator")
        if not isinstance(contract, dict):
            raise StateConflictError("Confirmation contract is incomplete.")
        locator = await require_unique(
            resolve_locator(page, contract), contract_key="confirmation_reference"
        )
        return {
            "confirmation_reference": (await locator.inner_text())[:500],
            "page_fingerprint": identity.fingerprint,
            "safe_url_path": identity.safe_url_path,
        }

    async def close_session(self, page: Any) -> None:
        await page.close()
