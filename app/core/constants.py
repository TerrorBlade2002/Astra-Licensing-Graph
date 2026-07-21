"""Project-wide constants that are not domain enumerations."""

APP_NAME_DEFAULT = "astra-licensing-automation"

LICENSING_MAILBOX_ADDRESS = "astralicensing@astraglobal.com"

# Shared-mailbox folder names managed by the licensing workflow.
KNOWN_MAILBOX_FOLDERS: tuple[str, ...] = (
    "Inbox",
    "01_Inbox_Unprocessed",
    "02_RASI",
    "03_Cornerstone_Bonds",
    "04_NMLS",
    "05_Regulators",
    "06_Invoices",
    "07_Proof_Received",
    "08_Info_Required",
    "09_Internal_Followups",
    "10_Completed",
    "99_Errors_Review",
)

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Maximum characters of an opaque delta link that may appear in logs.
DELTA_LINK_LOG_PREFIX_LENGTH = 32
