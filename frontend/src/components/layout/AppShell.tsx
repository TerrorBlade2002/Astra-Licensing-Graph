import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../../api/client";
import type { Actor } from "../../types";
import { entraEnabled, msal } from "../../auth/msal";

const links = [
  ["/licensing", "Licensing overview", "L"],
  ["/licensing/tracker", "Current tracker", "T"],
  ["/licensing/licenses", "Licenses", "I"],
  ["/licensing/cases", "Compliance cases", "C"],
  ["/licensing/correspondence", "Correspondence review", "M"],
  ["/licensing/calendar", "Compliance calendar", "D"],
  ["/licensing/requirements", "Requirement matrix", "R"],
  ["/licensing/information", "Information registry", "K"],
  ["/licensing/packets", "Packet builder", "P"],
  ["/licensing/forms", "Form preparation", "F"],
  ["/portals", "Portal governance", "G"],
  ["/portal-runs", "Portal assistance", "A"],
  ["/licensing/sources", "Source governance", "S"],
  ["/licensing/data-quality", "Data quality", "Q"],
  ["/communications/drafts", "Draft queue", "✎"],
  ["/communications/approvals", "Send approval", "✓"],
  ["/communications/status", "Communication status", "↗"],
  ["/", "Overview", "⌂"],
  ["/reviews", "Review queue", "◎"],
  ["/tasks", "Task board", "□"],
  ["/documents", "Documents", "◇"],
  ["/evaluation", "Evaluation", "△"],
  ["/admin/rules", "Rule studio", "⚙"],
] as const;
export function AppShell() {
  const { data } = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Actor>("/auth/me"),
  });
  const env = import.meta.env.VITE_APP_ENV ?? "local";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <div>
            <strong>Astra</strong>
            <small>Licensing operations</small>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {links.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/" || to === "/licensing"}>
              <span aria-hidden>{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="status-dot" />
          Human send approval required
          <p>Accepted, verified, and delivered remain distinct.</p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">Licensing control plane</span>
            <b>Evidence to action, with judgment in the loop</b>
          </div>
          <div className="user">
            <span className="env">{env}</span>
            <div className="avatar">
              {(data?.display_name ?? "D").slice(0, 1)}
            </div>
            <div>
              <strong>{data?.display_name ?? "Development user"}</strong>
              <small>
                {data?.roles.at(-1)?.replace("Licensing.", "") ?? "Loading…"}
              </small>
            </div>
            {entraEnabled && (
              <button
                className="icon-button"
                aria-label="Sign out"
                onClick={() => void msal.logoutRedirect()}
              >
                ↗
              </button>
            )}
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  );
}
