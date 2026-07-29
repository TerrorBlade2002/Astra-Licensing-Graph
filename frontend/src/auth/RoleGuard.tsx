import type { PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Actor } from "../types";

const hierarchy = [
  "Licensing.Reader",
  "Licensing.Reviewer",
  "Licensing.Manager",
  "Licensing.Admin",
];
function allowedForRole(actual: string[], requiredRole: string) {
  if (requiredRole === "Licensing.Sender")
    return (
      actual.includes("Licensing.Sender") ||
      actual.includes("Licensing.Manager")
    );
  const required = hierarchy.indexOf(requiredRole);
  return (
    required >= 0 && actual.some((role) => hierarchy.indexOf(role) >= required)
  );
}
export function RoleGuard({
  role,
  children,
}: PropsWithChildren<{ role: string }>) {
  const { data } = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Actor>("/auth/me"),
  });
  if (!data) return null;
  const allowed = allowedForRole(data.roles, role);
  return allowed ? (
    children
  ) : (
    <main className="empty-state">
      <h2>Access restricted</h2>
      <p>This page requires the {role} role.</p>
    </main>
  );
}
