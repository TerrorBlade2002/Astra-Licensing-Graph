"""Portal-safe classification taxonomy."""

from fastapi import APIRouter

from app.api.dependencies import ActorDep
from app.classification.taxonomy import LICENSE_PHRASES, US_STATES, VALID_DESTINATIONS
from app.domain.enums import EmailType

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/email-types")
async def email_types(actor: ActorDep) -> list[str]:
    return [e.value for e in EmailType]


@router.get("/states")
async def states(actor: ActorDep) -> list[str]:
    return list(US_STATES.values())


@router.get("/license-types")
async def licenses(actor: ActorDep) -> list[str]:
    return sorted(set(LICENSE_PHRASES.values()))


@router.get("/document-types")
async def documents(actor: ActorDep) -> list[str]:
    return [
        "STATE_CHECKLIST",
        "LICENSE_CERTIFICATE",
        "BOND",
        "INVOICE",
        "CORRESPONDENCE",
        "UNCLASSIFIED",
    ]


@router.get("/destination-folders")
async def destinations(actor: ActorDep) -> list[str]:
    return VALID_DESTINATIONS


@router.get("/vendors")
async def vendors(actor: ActorDep) -> list[str]:
    return ["RASI", "NMLS"]
