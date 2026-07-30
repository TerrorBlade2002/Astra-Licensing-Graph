import { InteractionRequiredAuthError } from "@azure/msal-browser";
import { apiScope, entraEnabled, loginRequest, msal } from "../auth/msal";

// An unset *or empty* build variable falls back to the dev-server proxy path;
// an empty string would otherwise send every request to the site root.
const baseUrl = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public correlationId?: string,
  ) {
    super(message);
  }
}

async function token(forceRefresh = false): Promise<string | undefined> {
  if (!entraEnabled) return undefined;
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  if (!account) {
    await msal.loginRedirect(loginRequest);
    return undefined;
  }
  try {
    return (
      await msal.acquireTokenSilent({
        account,
        scopes: [apiScope],
        forceRefresh,
      })
    ).accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError)
      await msal.acquireTokenRedirect({ account, scopes: [apiScope] });
    throw error;
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  reacquired = false,
): Promise<T> {
  const accessToken = await token(reacquired);
  const correlationId = crypto.randomUUID();
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Correlation-ID": correlationId,
      ...(accessToken
        ? { Authorization: `Bearer ${accessToken}` }
        : {
            "X-Actor-Id": "portal-dev",
            "X-Actor-Roles":
              "Licensing.Admin,Licensing.Manager,Licensing.Reviewer,Licensing.Sender,Information.Owner,Portal.Operator,Portal.FinalSubmitter,Payment.Approver,Authorized.Signatory",
          }),
      ...init.headers,
    },
  });
  if (
    response.status === 401 &&
    entraEnabled &&
    !reacquired &&
    (init.method ?? "GET") === "GET"
  )
    return api<T>(path, init, true);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      error?: { message?: string; correlation_id?: string };
    };
    throw new ApiError(
      response.status,
      body.error?.message ?? `Request failed (${response.status})`,
      body.error?.correlation_id ?? correlationId,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function apiForm<T>(path: string, body: FormData): Promise<T> {
  const accessToken = await token();
  const correlationId = crypto.randomUUID();
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    body,
    headers: {
      "X-Correlation-ID": correlationId,
      ...(accessToken
        ? { Authorization: `Bearer ${accessToken}` }
        : {
            "X-Actor-Id": "portal-dev",
            "X-Actor-Roles":
              "Licensing.Admin,Licensing.Manager,Licensing.Reviewer,Information.Owner,Portal.Operator,Portal.FinalSubmitter,Payment.Approver,Authorized.Signatory",
          }),
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: { message?: string; correlation_id?: string };
    };
    throw new ApiError(
      response.status,
      payload.error?.message ?? `Request failed (${response.status})`,
      payload.error?.correlation_id ?? correlationId,
    );
  }
  return response.json() as Promise<T>;
}

export async function apiDownload(path: string, fallbackName: string) {
  const accessToken = await token();
  const response = await fetch(`${baseUrl}${path}`, {
    headers: accessToken
      ? { Authorization: `Bearer ${accessToken}` }
      : {
          "X-Actor-Id": "portal-dev",
          "X-Actor-Roles":
            "Licensing.Admin,Licensing.Manager,Licensing.Reviewer,Information.Owner,Portal.Operator,Portal.FinalSubmitter,Payment.Approver,Authorized.Signatory",
        },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: { message?: string };
    };
    throw new ApiError(
      response.status,
      payload.error?.message ?? `Download failed (${response.status})`,
    );
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = match?.[1] ?? fallbackName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}
