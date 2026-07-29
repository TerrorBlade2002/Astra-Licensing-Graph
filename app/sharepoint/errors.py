"""Sanitized SharePoint-domain errors."""


class SharePointError(RuntimeError):
    code = "sharepoint_error"


class SharePointConfigurationError(SharePointError):
    code = "sharepoint_configuration_error"


class SharePointPermissionError(SharePointError):
    code = "sharepoint_permission_denied"


class SharePointConcurrencyError(SharePointError):
    code = "sharepoint_concurrency_conflict"


class UploadSessionExpiredError(SharePointError):
    code = "upload_session_expired"


class UploadProtocolError(SharePointError):
    code = "upload_protocol_error"
