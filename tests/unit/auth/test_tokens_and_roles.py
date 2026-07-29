import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.roles import Role, has_role
from app.auth.tokens import EntraTokenValidator
from tests.conftest import make_test_settings


class Cache:
    def __init__(self, jwk: dict[str, object]) -> None:
        self.jwk = jwk

    async def key(self, kid: str) -> dict[str, object]:
        assert kid == "kid-1"
        return self.jwk


@pytest.mark.asyncio
async def test_validates_signature_issuer_tenant_audience_and_scope() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "kid-1"
    tenant = "11111111-1111-1111-1111-111111111111"
    audience = "api://astra-backend"
    settings = make_test_settings(
        "postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing_test",
        AUTH_MODE="entra",
        ENTRA_TENANT_ID=tenant,
        ENTRA_API_AUDIENCE=audience,
    )
    now = datetime.now(tz=UTC)
    token = jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{tenant}/v2.0",
            "aud": audience,
            "tid": tenant,
            "oid": "object-1",
            "scp": "Licensing.Access",
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
        },
        private,
        algorithm="RS256",
        headers={"kid": "kid-1"},
    )
    claims = await EntraTokenValidator(settings, Cache(jwk)).validate(token)  # type: ignore[arg-type]
    assert claims["oid"] == "object-1"
    assert has_role((Role.ADMIN.value,), Role.REVIEWER)
    assert not has_role((Role.READER.value,), Role.REVIEWER)
