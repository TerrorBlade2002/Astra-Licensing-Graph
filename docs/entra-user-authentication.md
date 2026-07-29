# Entra user authentication

Use two single-tenant app registrations. **Astra Licensing Backend API** exposes delegated scope `api://{backend-client-id}/Licensing.Access` and app roles `Licensing.Reader`, `Licensing.Reviewer`, `Licensing.Manager`, and `Licensing.Admin`. **Astra Licensing Portal SPA** uses authorization code with PKCE, has only approved local/staging/production SPA redirect URIs, and receives delegated `Licensing.Access`. Never add a SPA secret or reuse the mailbox-ingestion service principal.

The portal uses MSAL session storage, silent acquisition, and sends the API **access token**. The backend validates RS256 signature, OpenID-discovered JWKS, issuer, tenant, audience, expiry, not-before, object ID, and scope/roles. Unknown key IDs trigger one metadata refresh; failures close access. Database role snapshots are diagnostic, never authoritative.

## Administrator setup

1. Create/identify the backend API registration; expose `Licensing.Access`.
2. Add the four application roles with user/group assignment enabled.
3. Create the SPA registration and add exact local, staging, and production redirect URIs.
4. Grant the SPA delegated backend scope; do not enable implicit grants.
5. Assign test users/groups to roles and configure tenant, audience, issuer, client ID, and scope.
6. Verify PKCE sign-in and inspect that the API token audience is the backend, not the SPA.
7. Verify Reader is denied review, Reviewer can decide/create tasks, Manager can assign, and Admin can manage versioned configuration.
8. Revoke test access and record app owners/approvers.

Production refuses `AUTH_MODE=development` or missing tenant/audience. Rotate access through Entra assignments; there are no application user passwords.
