"""Pre-deploy configuration gate.

    python -m app.cli.check_deployment

Loads the environment exactly as the application does, so a missing or unsafe
variable fails the deployment before migrations run instead of after the first
request. Prints a JSON report and exits non-zero on any failure.

It never prints a secret value — only whether one is present.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def evaluate(settings: Settings) -> list[dict[str, Any]]:
    """Presence checks that only matter for a deployed environment."""
    checks: list[dict[str, Any]] = []
    deployed = settings.app_env in ("staging", "production")

    checks.append(
        _check("database_url", bool(settings.database_url), "DATABASE_URL is configured.")
    )
    if deployed:
        checks.append(
            _check(
                "backend_url",
                bool(settings.backend_url),
                "BACKEND_URL must name the public API domain.",
            )
        )
        checks.append(
            _check(
                "frontend_url",
                bool(settings.frontend_url),
                "FRONTEND_URL must name the public portal domain.",
            )
        )
        checks.append(
            _check(
                "cors_origins",
                bool(settings.cors_origins),
                "CORS_ORIGINS must list the portal origin.",
            )
        )
        checks.append(
            _check(
                "auth_mode",
                settings.auth_mode == "entra",
                "Deployed environments authenticate with Entra.",
            )
        )
        checks.append(
            _check(
                "entra_configuration",
                bool(settings.entra_tenant_id and settings.entra_api_audience),
                "ENTRA_TENANT_ID and ENTRA_API_AUDIENCE are required.",
            )
        )
        checks.append(
            _check(
                "public_base_url",
                settings.public_base_url.startswith("https://"),
                "PUBLIC_BASE_URL must be the HTTPS webhook address.",
            )
        )

    if settings.graph_enabled:
        credential_present = (
            bool(settings.graph_client_secret)
            if settings.graph_credential_mode == "client_secret"
            else bool(settings.graph_certificate_path and settings.graph_certificate_thumbprint)
        )
        checks.append(
            _check("graph_credential", credential_present, "A Graph credential is configured.")
        )
        checks.append(
            _check(
                "graph_mailbox",
                bool(settings.graph_expected_mailbox_address),
                "GRAPH_MAILBOX pins access to the licensing mailbox.",
            )
        )
    if settings.sharepoint_enabled:
        missing = [name for name, value in settings.sharepoint_drive_ids.items() if not value]
        checks.append(
            _check(
                "sharepoint_drives",
                not missing,
                "All SharePoint drive IDs are configured."
                if not missing
                else f"Missing drive IDs: {', '.join(sorted(missing))}.",
            )
        )
    if settings.ai_classification_enabled or settings.response_ai_drafting_enabled:
        checks.append(
            _check(
                "openai_key",
                bool(settings.openai_api_key),
                "OPENAI_API_KEY is present (value never printed).",
            )
        )
    if settings.portal_automation_enabled:
        checks.append(
            _check(
                "portal_allowed_hosts",
                bool(settings.portal_allowed_hosts),
                "PORTAL_ALLOWED_HOSTS restricts portal automation.",
            )
        )

    # Boundaries that must hold in every environment, restated here so the
    # deployment log shows them explicitly.
    checks.append(
        _check(
            "send_approval_required",
            settings.communication_require_send_approval,
            "Outbound email requires explicit send approval.",
        )
    )
    checks.append(
        _check(
            "final_submit_human_only",
            settings.portal_final_submit_human_only,
            "Final portal submission stays with a human.",
        )
    )
    checks.append(
        _check(
            "external_submission_disabled",
            not settings.form_external_submission_enabled,
            "Autonomous external filing is disabled.",
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="Print the report on a single line.")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "configuration_invalid",
                    "problems": [error["msg"] for error in exc.errors()],
                },
                indent=None if args.compact else 2,
            )
        )
        return 1

    checks = evaluate(settings)
    ok = all(check["status"] == "PASS" for check in checks)
    print(
        json.dumps(
            {
                "ok": ok,
                "app_env": settings.app_env,
                "app_version": settings.app_version,
                "checks": checks,
            },
            indent=None if args.compact else 2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
