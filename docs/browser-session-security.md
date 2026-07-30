# Browser session security

The browser worker runs separately from FastAPI. Each database browser-session row maps to one process-local Playwright browser and isolated context owned by one internal user and one worker.

- Passwords, MFA codes, cookies, tokens, local storage, session storage, and Playwright storage state are never accepted by an API or written to PostgreSQL.
- Session-state persistence is disabled for Milestone 7. If it is enabled in a future environment, startup requires an encryption-key reference.
- Browser profiles live beneath `BROWSER_TEMP_ROOT`, use random identifiers, and are deleted when the session closes or expires.
- Downloads and service workers are disabled. Remote debugging is forbidden.
- Navigation is HTTPS-only, pinned to the approved hostname, and checked against private, loopback, link-local, and reserved DNS results. Local HTTP is allowed only in the test environment.
- The browser session can be accessed only by its assigned operator. A handoff assigned to another user pauses and detaches the browser-session reference rather than sharing authenticated state.
- Inactivity and maximum-lifetime expiry close the live context and block the run.

The browser worker container is non-root, read-only, capability-dropped, and uses a dedicated no-exec temporary filesystem. Screenshots, video, and DOM capture are disabled by default. Unknown-page diagnostics retain only a sanitized DOM hash and size.

