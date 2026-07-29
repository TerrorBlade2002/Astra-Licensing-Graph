import {
  BrowserCacheLocation,
  PublicClientApplication,
} from "@azure/msal-browser";

const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID ?? "";
const clientId = import.meta.env.VITE_ENTRA_SPA_CLIENT_ID ?? "";
export const apiScope = import.meta.env.VITE_ENTRA_API_SCOPE ?? "";
export const entraEnabled = Boolean(tenantId && clientId && apiScope);

export const msal = new PublicClientApplication({
  auth: {
    clientId: clientId || "00000000-0000-0000-0000-000000000000",
    authority: `https://login.microsoftonline.com/${tenantId || "organizations"}`,
    redirectUri: window.location.origin,
  },
  cache: { cacheLocation: BrowserCacheLocation.SessionStorage },
  system: { allowPlatformBroker: false },
});

export const loginRequest = { scopes: [apiScope].filter(Boolean) };
