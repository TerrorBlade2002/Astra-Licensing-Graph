"""Recipient normalization and policy enforcement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.communications.enums import RecipientMode
from app.core.config import Settings

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class RecipientPolicyResult:
    allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


class RecipientPolicyService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        *,
        mode: str,
        to_recipients: list[dict[str, Any]],
        cc_recipients: list[dict[str, Any]],
        bcc_recipients: list[dict[str, Any]],
        reply_all_reviewed: bool = False,
        bcc_authorized: bool = False,
        blocked_domains: set[str] | None = None,
        internal_domains: set[str] | None = None,
        policy_rules: list[Any] | None = None,
        manager_approved: bool = False,
        enforce_manager_rules: bool = False,
    ) -> RecipientPolicyResult:
        blockers: list[str] = []
        warnings: list[str] = []
        all_recipients = to_recipients + cc_recipients + bcc_recipients
        addresses = [str(item.get("address") or "").strip().lower() for item in all_recipients]
        if not to_recipients:
            blockers.append("RECIPIENT_MISSING")
        if any(not EMAIL.fullmatch(address) for address in addresses):
            blockers.append("RECIPIENT_POLICY_BLOCK")
        if len(to_recipients) > self.settings.communication_max_to_recipients:
            blockers.append("RECIPIENT_POLICY_BLOCK")
        if len(cc_recipients) > self.settings.communication_max_cc_recipients:
            blockers.append("RECIPIENT_POLICY_BLOCK")
        if len(all_recipients) > self.settings.communication_max_total_recipients:
            blockers.append("RECIPIENT_POLICY_BLOCK")
        domains = {address.rsplit("@", 1)[-1] for address in addresses if "@" in address}
        if blocked_domains and domains & {item.lower() for item in blocked_domains}:
            blockers.append("RECIPIENT_POLICY_BLOCK")
        if mode == RecipientMode.REPLY_ALL and (
            not self.settings.communication_reply_all_enabled or not reply_all_reviewed
        ):
            blockers.append("REPLY_ALL_NOT_APPROVED")
        if bcc_recipients and (not self.settings.communication_bcc_enabled or not bcc_authorized):
            blockers.append("BCC_NOT_AUTHORIZED")
        if internal_domains is not None:
            external = domains - {item.lower() for item in internal_domains}
            if external:
                warnings.append("EXTERNAL_RECIPIENT")
        else:
            external = set()
        for rule in sorted(
            (value for value in policy_rules or [] if value.enabled),
            key=lambda value: value.priority,
        ):
            conditions = rule.conditions if isinstance(rule.conditions, dict) else {}
            configured_values = conditions.get("values", conditions.get("domains", []))
            if not isinstance(configured_values, (list, tuple, set)):
                configured_values = []
            values = {
                str(value).strip().lower() for value in configured_values if str(value).strip()
            }
            matches = False
            if rule.rule_type == "BLOCKED_DOMAIN":
                matches = bool(domains & values)
            elif rule.rule_type == "BLOCKED_ADDRESS":
                matches = bool(set(addresses) & values)
            elif rule.rule_type == "ALLOWED_DOMAIN" and values:
                matches = bool(domains - values)
            elif rule.rule_type == "ALLOWED_ADDRESS" and values:
                matches = bool(set(addresses) - values)
            elif rule.rule_type == "INTERNAL_ONLY":
                permitted = values or {value.lower() for value in internal_domains or set()}
                matches = bool(domains - permitted)
            elif rule.rule_type == "EXTERNAL_REQUIRES_MANAGER":
                matches = bool(external) and enforce_manager_rules and not manager_approved
            elif rule.rule_type == "MAX_RECIPIENTS":
                try:
                    maximum = int(conditions.get("maximum", conditions.get("max", 0)) or 0)
                except (TypeError, ValueError):
                    maximum = 0
                matches = maximum > 0 and len(all_recipients) > maximum
            elif rule.rule_type == "BCC_DISABLED":
                matches = bool(bcc_recipients)
            elif rule.rule_type == "REPLY_ALL_REQUIRES_APPROVAL":
                matches = mode == RecipientMode.REPLY_ALL and not reply_all_reviewed
            if not matches:
                continue
            if str(rule.action).upper() in {"WARN", "FLAG"}:
                warnings.append(rule.rule_key)
            else:
                blockers.append("RECIPIENT_POLICY_BLOCK")
        return RecipientPolicyResult(not blockers, tuple(dict.fromkeys(blockers)), tuple(warnings))
