"""Application role names and inheritance."""

from enum import StrEnum


class Role(StrEnum):
    READER = "Licensing.Reader"
    ANALYST = "Licensing.Analyst"
    REVIEWER = "Licensing.Reviewer"
    SENDER = "Licensing.Sender"
    MANAGER = "Licensing.Manager"
    ADMIN = "Licensing.Admin"
    COUNSEL = "Licensing.Counsel"
    INFORMATION_OWNER = "Information.Owner"
    AUTHORIZED_SIGNATORY = "Authorized.Signatory"


#: Linear seniority ladder: Reader < Analyst < Reviewer < Manager < Admin.
_LEVEL = {
    Role.READER: 1,
    Role.ANALYST: 2,
    Role.REVIEWER: 3,
    Role.MANAGER: 4,
    Role.ADMIN: 5,
}

#: Roles conferring a distinct authority rather than a seniority level. None is
#: implied by Admin: administering taxonomies does not make someone counsel, a
#: data steward, or an authorized signer.
_STANDALONE_ROLES = frozenset(
    {Role.SENDER, Role.COUNSEL, Role.INFORMATION_OWNER, Role.AUTHORIZED_SIGNATORY}
)


def has_role(actual: tuple[str, ...], required: Role) -> bool:
    # Send authority is deliberately not inherited by Admin. Only the dedicated
    # Sender role or Manager role can approve/queue correspondence.
    if required is Role.SENDER:
        return Role.SENDER.value in actual or Role.MANAGER.value in actual
    # Counsel sign-off, information ownership, and signature authority are
    # explicit grants; seniority never substitutes for them.
    if required in _STANDALONE_ROLES:
        return required.value in actual
    return any(_LEVEL.get(Role(value), 0) >= _LEVEL[required] for value in actual if value in Role)


def has_any_role(actual: tuple[str, ...], required: tuple[Role, ...]) -> bool:
    """True when the actor satisfies at least one of ``required``."""
    return any(has_role(actual, role) for role in required)
