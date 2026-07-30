import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Milestone 8: the portal must resolve its API base URL from build
 * configuration, load authentication in both modes, and expose the deployed
 * routes. The bundle-secret scan runs in CI against frontend/dist.
 */
describe("deployment configuration", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("calls the configured absolute API base URL", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.invalid/api/v1");
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        void input;
        return new Response("{}", { status: 200 });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("../api/client");
    await api("/operations/status");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example.invalid/api/v1/operations/status",
    );
  });

  it("strips a trailing slash so paths are never doubled", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.invalid/api/v1/");
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        void input;
        return new Response("{}", { status: 200 });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("../api/client");
    await api("/emails");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example.invalid/api/v1/emails",
    );
  });

  it("falls back to the dev-server proxy path when unset", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        void input;
        return new Response("{}", { status: 200 });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("../api/client");
    await api("/emails");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/emails");
  });

  it("loads authentication without Entra configuration", async () => {
    vi.stubEnv("VITE_ENTRA_TENANT_ID", "");
    vi.stubEnv("VITE_ENTRA_SPA_CLIENT_ID", "");
    vi.stubEnv("VITE_ENTRA_API_SCOPE", "");

    const { entraEnabled, msal } = await import("../auth/msal");
    expect(entraEnabled).toBe(false);
    expect(msal).toBeDefined();
  });

  it("enables Entra when every public value is present", async () => {
    vi.stubEnv("VITE_ENTRA_TENANT_ID", "11111111-1111-1111-1111-111111111111");
    vi.stubEnv(
      "VITE_ENTRA_SPA_CLIENT_ID",
      "22222222-2222-2222-2222-222222222222",
    );
    vi.stubEnv("VITE_ENTRA_API_SCOPE", "api://backend/Licensing.Access");

    const { entraEnabled, apiScope } = await import("../auth/msal");
    expect(entraEnabled).toBe(true);
    expect(apiScope).toBe("api://backend/Licensing.Access");
  });

  it("exposes the critical portal routes", async () => {
    const { router } = await import("../app/router");
    const paths = new Set(
      (router.routes[0]?.children ?? []).map((route) => route.path ?? "index"),
    );
    for (const path of [
      "reviews",
      "tasks",
      "documents",
      "licensing/tracker",
      "licensing/licenses",
      "licensing/cases",
      "licensing/import",
      "portal-runs",
    ]) {
      expect(paths).toContain(path);
    }
  }, 10_000);
});
