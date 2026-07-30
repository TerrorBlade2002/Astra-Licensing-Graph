"""Reviewed vendor or bond-provider portal adapter family."""

from app.portals.adapters.generic_assisted import GenericAssistedAdapter


class VendorPortalAssistedAdapter(GenericAssistedAdapter):
    adapter_key = "vendor-portal-assisted"
    supported_filing_types = frozenset()
