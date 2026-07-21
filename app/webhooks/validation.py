"""Graph webhook validation-token handling.

During subscription creation Graph POSTs `?validationToken=...` and expects
the URL-decoded token echoed back as text/plain within 10 seconds. The token
is opaque: it is never logged, persisted, or interpreted.
"""

from __future__ import annotations

from fastapi.responses import PlainTextResponse

MAX_VALIDATION_TOKEN_LENGTH = 2048


def validation_token_response(token: str) -> PlainTextResponse:
    # FastAPI/Starlette already URL-decoded the query parameter once.
    trimmed = token[:MAX_VALIDATION_TOKEN_LENGTH]
    return PlainTextResponse(content=trimmed, status_code=200)
