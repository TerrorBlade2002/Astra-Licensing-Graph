"""Application role names and inheritance."""

from enum import StrEnum


class Role(StrEnum):
    READER = "Licensing.Reader"
    REVIEWER = "Licensing.Reviewer"
    SENDER = "Licensing.Sender"
    MANAGER = "Licensing.Manager"
    ADMIN = "Licensing.Admin"


_LEVEL = {Role.READER: 1, Role.REVIEWER: 2, Role.MANAGER: 3, Role.ADMIN: 4}


def has_role(actual: tuple[str, ...], required: Role) -> bool:
    # Send authority is deliberately not inherited by Admin. Only the dedicated
    # Sender role or Manager role can approve/queue correspondence.
    if required is Role.SENDER:
        return Role.SENDER.value in actual or Role.MANAGER.value in actual
    return any(_LEVEL.get(Role(value), 0) >= _LEVEL[required] for value in actual if value in Role)
