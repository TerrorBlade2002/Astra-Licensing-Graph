# Entra ID sign-in

Portal sign-in and mailbox ingestion are separate concerns that happen to share
one app registration. Graph app-only access reads the licensing mailbox;
everything here is about who may open the portal and what they may do in it.

## Registration

| Item | Value |
| --- | --- |
| Tenant | `58b1714c-43be-4fb1-acbe-ea1ac4d8a850` |
| Application (client) ID | `996d8468-d4db-4963-967d-951a61832e9a` |
| Application ID URI | `api://996d8468-d4db-4963-967d-951a61832e9a` |
| Delegated scope | `Licensing.Access` |

One registration acts as both the SPA and the API it calls. That is why the
SPA's client id and the API's audience are the same GUID.

## Portal configuration

Under **Entra admin center → Applications → App registrations → this app**:

1. **Authentication → Add a platform → Single-page application**, redirect URI
   set to the portal origin with no trailing path. Leave the implicit-grant
   checkboxes clear; the portal uses PKCE.
2. **Expose an API** → set the Application ID URI, add the `Licensing.Access`
   scope (admins and users may consent), then add the same client id under
   *Authorized client applications* so the portal is pre-consented to its own
   API.
3. **App roles** → create one role per licensing role, allowed member type
   **Users/Groups**. The role's *Value* is what appears in the token and must
   match exactly: `Licensing.Admin`, `Licensing.Manager`, `Licensing.Reviewer`,
   `Licensing.Sender`. Optional standalone grants use the same rule:
   `Information.Owner`, `Portal.Operator`, `Payment.Approver`,
   `Authorized.Signatory`, `Portal.FinalSubmitter`, `Licensing.Counsel`.

Under **Enterprise applications → this app → Users and groups**, assign each
person the roles they need — one assignment per role. This step needs a
directory administrator; creating the roles does not.

## Token versions

A registration left at `requestedAccessTokenVersion: null` issues v1 access
tokens from `https://sts.windows.net/<tenant>/`, with `aud` as the client id.
Setting it to `2` issues v2 tokens from
`https://login.microsoftonline.com/<tenant>/v2.0`, with `aud` as the App ID
URI.

Both forms are accepted, because both are Microsoft-signed for the same tenant
and the same API, and sign-in should not depend on which one an administrator
happened to configure. The tenant claim is checked separately, so a token from
another directory is still rejected.

## Variables

Backend, worker, and scheduler:

| Variable | Value |
| --- | --- |
| `AUTH_MODE` | `entra` |
| `ENTRA_TENANT_ID` | tenant GUID |
| `ENTRA_API_CLIENT_ID` | application (client) ID |
| `ENTRA_API_AUDIENCE` | `api://<client-id>` |
| `ENTRA_API_SCOPE` | `Licensing.Access` (short name, as it appears in `scp`) |

Frontend — these are inlined into the bundle at build time, so the service must
be **redeployed**, not just restarted, after they change:

| Variable | Value |
| --- | --- |
| `VITE_ENTRA_TENANT_ID` | tenant GUID |
| `VITE_ENTRA_SPA_CLIENT_ID` | application (client) ID |
| `VITE_ENTRA_API_SCOPE` | `api://<client-id>/Licensing.Access` (full URI) |

None of these are secrets. The portal has no client secret and must never be
given one.

Until all three `VITE_ENTRA_*` values are present the portal treats Entra as
disabled and falls back to development actor headers, which only work when the
backend is also in development auth mode.

## Before roles are assigned

A signed-in account with no app role holds a valid token and can read, but
every role-gated action returns 403 and the portal shows *Access restricted* in
place of those pages. The shell displays a notice explaining that an
administrator needs to assign roles. This is the expected state between
enabling sign-in and completing role assignment.

## Verifying

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$BACKEND_URL/api/v1/auth/me"
```

`401` is correct: the endpoint now requires a bearer token. A `503` means the
backend is still in development auth mode with a deployed `APP_ENV`.

Signed in, `GET /api/v1/auth/me` returns the object id, display name, the roles
from the token, and the capabilities derived from them. That response is the
authoritative answer to "what am I allowed to do" — the portal renders its
navigation from it.

## Reverting

Set `AUTH_MODE=development` and `APP_ENV=local` on the backend. Development
actor headers are refused whenever `APP_ENV` is anything other than `local` or
`test`, so both must move together.
