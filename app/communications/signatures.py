"""Approved signatures; values contain no secrets or dynamic code."""

SIGNATURES: dict[str, str] = {
    "licensing-standard": "Regards,\nAstra Licensing Team",
}


def apply_signature(body: str, signature_key: str) -> str:
    signature = SIGNATURES.get(signature_key)
    if signature is None:
        raise ValueError("Signature key is not approved.")
    return f"{body.rstrip()}\n\n{signature}"
