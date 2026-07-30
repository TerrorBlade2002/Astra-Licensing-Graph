"""Adapter lookup by reviewed adapter key."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import StateConflictError
from app.portals.adapters.base import PortalAdapter
from app.portals.adapters.generic_assisted import GenericAssistedAdapter
from app.portals.adapters.nmls import NMLSAssistedAdapter
from app.portals.adapters.state_portal import StatePortalAssistedAdapter
from app.portals.adapters.vendor_portal import VendorPortalAssistedAdapter

_ADAPTERS: dict[str, type[PortalAdapter]] = {
    GenericAssistedAdapter.adapter_key: GenericAssistedAdapter,
    NMLSAssistedAdapter.adapter_key: NMLSAssistedAdapter,
    StatePortalAssistedAdapter.adapter_key: StatePortalAssistedAdapter,
    VendorPortalAssistedAdapter.adapter_key: VendorPortalAssistedAdapter,
}


def build_adapter(
    adapter_key: str, *, locator_contract: dict[str, Any], contract_version: str
) -> PortalAdapter:
    adapter_type = _ADAPTERS.get(adapter_key)
    if adapter_type is None:
        raise StateConflictError(f"Unknown portal adapter {adapter_key!r}.")
    return adapter_type(locator_contract=locator_contract, contract_version=contract_version)
