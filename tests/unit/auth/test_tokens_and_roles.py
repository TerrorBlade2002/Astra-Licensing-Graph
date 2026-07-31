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


TENANT = "22222222-2222-2222-2222-222222222222"
CLIENT_ID = "996d8468-d4db-4963-967d-951a61832e9a"


def _signing_material() -> tuple[object, dict[str, object]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "kid-1"
    return private, jwk


def _settings() -> object:
    return make_test_settings(
        "postgresql+asyncpg://astra:astra_local_dev@localhost:5442/astra_licensing_test",
        AUTH_MODE="entra",
        ENTRA_TENANT_ID=TENANT,
        ENTRA_API_CLIENT_ID=CLIENT_ID,
        ENTRA_API_AUDIENCE=f"api://{CLIENT_ID}",
    )


def _token(private: object, *, issuer: str, audience: str) -> str:
    now = datetime.now(tz=UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "tid": TENANT,
            "oid": "object-1",
            "scp": "Licensing.Access",
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
        },
        private,
        algorithm="RS256",
        headers={"kid": "kid-1"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issuer",
    [
        f"https://login.microsoftonline.com/{TENANT}/v2.0",
        f"https://sts.windows.net/{TENANT}/",
    ],
)
@pytest.mark.parametrize("audience", [f"api://{CLIENT_ID}", CLIENT_ID])
async def test_both_token_versions_of_the_same_registration_are_accepted(
    issuer: str, audience: str
) -> None:
    """A registration issues v1 or v2 tokens depending on its manifest.

    Both forms name the same tenant and the same API, so sign-in must not
    depend on which one an administrator happened to configure.
    """
    private, jwk = _signing_material()
    claims = await EntraTokenValidator(_settings(), Cache(jwk)).validate(  # type: ignore[arg-type]
        _token(private, issuer=issuer, audience=audience)
    )
    assert claims["oid"] == "object-1"


@pytest.mark.asyncio
async def test_another_tenants_issuer_is_rejected() -> None:
    private, jwk = _signing_material()
    other = "33333333-3333-3333-3333-333333333333"
    with pytest.raises(ValueError, match="issuer"):
        await EntraTokenValidator(_settings(), Cache(jwk)).validate(  # type: ignore[arg-type]
            _token(
                private,
                issuer=f"https://login.microsoftonline.com/{other}/v2.0",
                audience=f"api://{CLIENT_ID}",
            )
        )


@pytest.mark.asyncio
async def test_a_token_minted_for_a_different_api_is_rejected() -> None:
    private, jwk = _signing_material()
    with pytest.raises(jwt.InvalidAudienceError):
        await EntraTokenValidator(_settings(), Cache(jwk)).validate(  # type: ignore[arg-type]
            _token(
                private,
                issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
                audience="api://some-other-api",
            )
        )
