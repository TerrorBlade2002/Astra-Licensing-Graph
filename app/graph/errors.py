"""Sanitized Graph error types.

GraphApiError deliberately carries only safe fields: no Authorization header,
no token, no secret, and never a full response body that could contain email
content.
"""

from __future__ import annotations

from app.core.exceptions import DomainError

RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class GraphError(DomainError):
    code = "graph_error"
    http_status = 502


class GraphApiError(GraphError):
    """A Graph HTTP call failed. Contains only sanitized diagnostics."""

    code = "graph_api_error"

    def __init__(
        self,
        *,
        status_code: int,
        graph_error_code: str | None = None,
        safe_message: str = "Microsoft Graph request failed.",
        request_id: str | None = None,
        client_request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(
            safe_message,
            details={
                "status_code": status_code,
                "graph_error_code": graph_error_code,
                "request_id": request_id,
                "client_request_id": client_request_id,
            },
        )
        self.status_code = status_code
        self.graph_error_code = graph_error_code
        self.safe_message = safe_message
        self.request_id = request_id
        self.client_request_id = client_request_id
        self.retry_after_seconds = retry_after_seconds

    @property
    def is_retryable(self) -> bool:
        return self.status_code in RETRYABLE_STATUS_CODES


class GraphAuthError(GraphError):
    """Token acquisition failed or 401 persisted after one forced refresh."""

    code = "graph_auth_error"

    def __init__(self, safe_message: str, *, error_code: str | None = None) -> None:
        super().__init__(safe_message, details={"error_code": error_code})
        self.error_code = error_code


class GraphResponseInvalidError(GraphError):
    """Graph returned a structurally invalid response (non-retryable)."""

    code = "graph_response_invalid"


class DeltaUrlValidationError(GraphError):
    """A saved delta/next link failed the security validation rules."""

    code = "delta_url_invalid"


class DeltaStateInvalidError(GraphError):
    """Graph rejected the sync token; a rebaseline is required."""

    code = "delta_state_invalid"


class EvidenceLimitExceededError(DomainError):
    code = "evidence_limit_exceeded"
    http_status = 413


# Graph error codes that mean the delta token is no longer usable.
DELTA_INVALID_ERROR_CODES = frozenset(
    {"syncstatenotfound", "resyncrequired", "syncstateinvalid", "badrequest_resync"}
)
