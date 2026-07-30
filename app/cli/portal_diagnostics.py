"""Safe portal registry diagnostics; never prints credentials or browser state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select

from app.cli.licensing_common import session_scope
from app.core.config import get_settings
from app.models import PortalAdapterVersion, PortalDefinition, PortalReviewVersion
from app.portals.enums import AdapterStatus, PortalReviewStatus
from app.portals.policies import approval_is_current


async def _list() -> list[dict[str, object]]:
    async with session_scope() as session:
        portals = list(
            await session.scalars(select(PortalDefinition).order_by(PortalDefinition.name))
        )
        return [
            {
                "portal_key": portal.portal_key,
                "portal_type": portal.portal_type,
                "hostname": portal.hostname,
                "status": portal.status,
                "automation_level": portal.approved_automation_level,
            }
            for portal in portals
        ]


async def _verify(portal_key: str) -> dict[str, object]:
    async with session_scope() as session:
        portal = await session.scalar(
            select(PortalDefinition).where(PortalDefinition.portal_key == portal_key)
        )
        if portal is None:
            return {"portal_key": portal_key, "valid": False, "reason": "not found"}
        review = await session.scalar(
            select(PortalReviewVersion).where(
                PortalReviewVersion.portal_definition_id == portal.id,
                PortalReviewVersion.status == PortalReviewStatus.APPROVED.value,
            )
        )
        adapter = await session.scalar(
            select(PortalAdapterVersion).where(
                PortalAdapterVersion.portal_definition_id == portal.id,
                PortalAdapterVersion.status == AdapterStatus.ACTIVE.value,
            )
        )
        if review is None:
            return {"portal_key": portal_key, "valid": False, "reason": "no active review"}
        decision = approval_is_current(
            portal_status=portal.status,
            review_status=review.status,
            valid_from=review.valid_from,
            valid_to=review.valid_to,
            terms_expires_at=portal.terms_review_expires_at,
        )
        return {
            "portal_key": portal.portal_key,
            "hostname": portal.hostname,
            "valid": decision.allowed,
            "reason": decision.reason,
            "review_version": review.version,
            "adapter_version": adapter.version if adapter else None,
            "browser_enabled": get_settings().browser_automation_enabled,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--portal-key", required=True)
    args = parser.parse_args(argv)
    result = (
        asyncio.run(_list()) if args.command == "list" else asyncio.run(_verify(args.portal_key))
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
