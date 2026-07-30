"""NMLS assistance boundary.

The adapter intentionally contains no terms, MFA, attestation, payment, or
submit action. Activation still requires a current portal-specific review.
"""

from app.portals.adapters.generic_assisted import GenericAssistedAdapter


class NMLSAssistedAdapter(GenericAssistedAdapter):
    adapter_key = "nmls-assisted"
    supported_filing_types = frozenset({"MU1", "MU2_COMPANY_PREPARATION", "MU3", "RENEWAL"})
