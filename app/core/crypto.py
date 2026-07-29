"""Envelope encryption and fingerprinting for sensitive governed values.

Design notes
------------
* **AES-256-GCM** with a random 96-bit nonce per encryption. Ciphertext is stored
  as an opaque, self-describing string so keys can rotate without a migration:
  ``v1:<key_id>:<b64url nonce>:<b64url ciphertext+tag>``.
* **Associated data** binds every ciphertext to the row that owns it
  (``<entity_type>:<entity_id>``). A ciphertext copied into a different row fails
  to decrypt, which stops silent cross-entity or cross-field value swapping.
* **Fingerprints** are keyed HMAC-SHA256 over a canonical encoding of the
  plaintext. They let the application detect "same answer as last version"
  without decrypting and without the offline-guessing exposure of a bare hash.
* Plaintext never reaches a log record, a metric label, or an AI prompt. Only
  :func:`redact` output is safe for display.

Key material resolution is intentionally explicit: production must supply real
keys through ``INFORMATION_ENCRYPTION_KEYS``. There is no implicit default key,
because a hard-coded fallback would silently "work" in production.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CIPHER_VERSION: Final = "v1"
_NONCE_BYTES: Final = 12
_KEY_BYTES: Final = 32
_KEY_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Environment variable holding a JSON object of ``{key_id: base64_32_byte_key}``.
KEYS_ENV_VAR: Final = "INFORMATION_ENCRYPTION_KEYS"
#: Environment variable naming which key id is used for new encryptions.
ACTIVE_KEY_ENV_VAR: Final = "INFORMATION_ENCRYPTION_ACTIVE_KEY"


class SensitiveDataError(Exception):
    """Raised when sensitive data cannot be protected or recovered."""


class EncryptionUnavailableError(SensitiveDataError):
    """No usable key material is configured."""


class DecryptionError(SensitiveDataError):
    """Ciphertext is malformed, bound to a different row, or the key is gone."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def canonical_bytes(value: Any) -> bytes:
    """Deterministically encode a value for fingerprinting.

    Sorted keys and separators without whitespace mean two structurally equal
    payloads always fingerprint identically regardless of construction order.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_sha256(value: Any) -> str:
    """Unkeyed digest, for non-secret content such as uploaded source files."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Keyring:
    """Immutable set of AES-256 keys with one designated active key."""

    keys: dict[str, bytes]
    active_key_id: str

    def __post_init__(self) -> None:
        if not self.keys:
            raise EncryptionUnavailableError("No encryption keys were supplied.")
        if self.active_key_id not in self.keys:
            raise EncryptionUnavailableError(
                f"Active key id {self.active_key_id!r} is not present in the keyring."
            )
        for key_id, material in self.keys.items():
            if not _KEY_ID_PATTERN.match(key_id):
                raise EncryptionUnavailableError(f"Invalid encryption key id {key_id!r}.")
            if len(material) != _KEY_BYTES:
                raise EncryptionUnavailableError(
                    f"Encryption key {key_id!r} must be exactly {_KEY_BYTES} bytes."
                )

    def key(self, key_id: str) -> bytes:
        try:
            return self.keys[key_id]
        except KeyError:
            raise DecryptionError(f"Encryption key {key_id!r} is not configured.") from None

    @classmethod
    def from_mapping(cls, mapping: dict[str, str], active_key_id: str | None = None) -> Keyring:
        decoded = {key_id: _b64d(material) for key_id, material in mapping.items()}
        active = active_key_id or next(iter(decoded))
        return cls(keys=decoded, active_key_id=active)

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None) -> Keyring:
        source = env if env is not None else dict(os.environ)
        raw = source.get(KEYS_ENV_VAR, "").strip()
        if not raw:
            raise EncryptionUnavailableError(
                f"{KEYS_ENV_VAR} must contain a JSON object of base64 32-byte keys."
            )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EncryptionUnavailableError(f"{KEYS_ENV_VAR} is not valid JSON.") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise EncryptionUnavailableError(f"{KEYS_ENV_VAR} must be a non-empty JSON object.")
        return cls.from_mapping(
            {str(k): str(v) for k, v in parsed.items()},
            source.get(ACTIVE_KEY_ENV_VAR) or None,
        )

    @classmethod
    def generate(cls, key_id: str = "test-key") -> Keyring:
        """Create an ephemeral keyring. For local development and tests only."""
        return cls(keys={key_id: os.urandom(_KEY_BYTES)}, active_key_id=key_id)


class SensitiveValueCipher:
    """Encrypts, decrypts, and fingerprints governed sensitive values."""

    def __init__(self, keyring: Keyring) -> None:
        self._keyring = keyring

    @property
    def active_key_id(self) -> str:
        return self._keyring.active_key_id

    @staticmethod
    def _aad(entity_type: str, entity_id: str) -> bytes:
        return f"{entity_type}:{entity_id}".encode()

    def encrypt(self, plaintext: Any, *, entity_type: str, entity_id: str) -> str:
        """Return an opaque ciphertext string bound to ``entity_type``/``entity_id``."""
        if not entity_type or not entity_id:
            raise SensitiveDataError("Sensitive values must be bound to an owning record.")
        key_id = self._keyring.active_key_id
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(self._keyring.key(key_id)).encrypt(
            nonce, canonical_bytes(plaintext), self._aad(entity_type, entity_id)
        )
        return f"{CIPHER_VERSION}:{key_id}:{_b64e(nonce)}:{_b64e(sealed)}"

    def decrypt(self, ciphertext: str, *, entity_type: str, entity_id: str) -> bytes:
        """Recover plaintext bytes, or raise :class:`DecryptionError`."""
        parts = (ciphertext or "").split(":")
        if len(parts) != 4 or parts[0] != CIPHER_VERSION:
            raise DecryptionError("Ciphertext envelope is malformed or of an unknown version.")
        _, key_id, nonce_b64, payload_b64 = parts
        try:
            nonce, payload = _b64d(nonce_b64), _b64d(payload_b64)
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            raise DecryptionError("Ciphertext envelope is not valid base64.") from exc
        try:
            return AESGCM(self._keyring.key(key_id)).decrypt(
                nonce, payload, self._aad(entity_type, entity_id)
            )
        except InvalidTag as exc:
            raise DecryptionError(
                "Ciphertext failed authentication; it may belong to another record."
            ) from exc

    def decrypt_text(self, ciphertext: str, *, entity_type: str, entity_id: str) -> str:
        return self.decrypt(ciphertext, entity_type=entity_type, entity_id=entity_id).decode(
            "utf-8"
        )

    def decrypt_json(self, ciphertext: str, *, entity_type: str, entity_id: str) -> Any:
        raw = self.decrypt(ciphertext, entity_type=entity_type, entity_id=entity_id)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8")

    def fingerprint(self, plaintext: Any) -> str:
        """Keyed digest usable for equality checks without decryption.

        Derived from the active key so a stolen database alone cannot be brute
        forced back to plaintext.
        """
        derived = hashlib.sha256(
            b"astra-fingerprint-v1:" + self._keyring.key(self._keyring.active_key_id)
        ).digest()
        return hmac.new(derived, canonical_bytes(plaintext), hashlib.sha256).hexdigest()


def redact(value: Any, *, keep_last: int = 0, placeholder: str = "*") -> str:
    """Produce a display-safe representation of a sensitive value.

    ``keep_last`` optionally reveals a short suffix (for example the last four
    digits of an account reference) so operators can distinguish records without
    exposing the value. Length is bucketed rather than exact to avoid leaking a
    precise length signal.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    if not text:
        return ""
    if keep_last > 0 and len(text) > keep_last:
        return f"{placeholder * 4}{text[-keep_last:]}"
    bucket = 4 if len(text) <= 8 else 8 if len(text) <= 32 else 12
    return placeholder * bucket


def mask_for_sensitivity(value: Any, sensitivity: str, *, keep_last: int = 0) -> str | None:
    """Return a display value appropriate to a sensitivity level.

    ``INTERNAL`` values are shown as-is; anything higher is redacted. Returning
    ``None`` for missing input keeps the caller from writing ``"None"`` into a
    display column.
    """
    from app.information_registry.enums import Sensitivity

    if value is None:
        return None
    if sensitivity == Sensitivity.INTERNAL.value:
        text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
        return text[:200]
    return redact(value, keep_last=keep_last)


def build_cipher(
    key_reference: str | None = None, *, env: dict[str, str] | None = None
) -> SensitiveValueCipher:
    """Build a cipher from environment key material.

    ``key_reference`` is recorded in settings for operational traceability (which
    KMS entry or vault path the keys came from); the material itself is read from
    the environment so it never lands in a settings dump or an error message.
    """
    keyring = Keyring.from_environment(env)
    return SensitiveValueCipher(keyring)


__all__ = [
    "ACTIVE_KEY_ENV_VAR",
    "CIPHER_VERSION",
    "KEYS_ENV_VAR",
    "DecryptionError",
    "EncryptionUnavailableError",
    "Keyring",
    "SensitiveDataError",
    "SensitiveValueCipher",
    "build_cipher",
    "canonical_bytes",
    "content_sha256",
    "mask_for_sensitivity",
    "redact",
]
