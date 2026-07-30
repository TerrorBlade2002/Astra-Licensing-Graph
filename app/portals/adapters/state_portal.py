"""Reviewed state/local regulator portal adapter family."""

from app.portals.adapters.generic_assisted import GenericAssistedAdapter


class StatePortalAssistedAdapter(GenericAssistedAdapter):
    adapter_key = "state-portal-assisted"
    supported_filing_types = frozenset()
