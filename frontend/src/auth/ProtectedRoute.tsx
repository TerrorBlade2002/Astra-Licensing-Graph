import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import type { PropsWithChildren } from "react";
import { entraEnabled, loginRequest } from "./msal";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const authenticated = useIsAuthenticated();
  const { instance } = useMsal();
  if (!entraEnabled || authenticated) return children;
  return (
    <main className="signin-panel">
      <div className="eyebrow">Secure organizational access</div>
      <h1>Astra Licensing Portal</h1>
      <p>
        Sign in with your Astra account to review licensing evidence and manage
        approved work.
      </p>
      <button
        className="primary"
        onClick={() => void instance.loginRedirect(loginRequest)}
      >
        Sign in with Microsoft
      </button>
    </main>
  );
}
