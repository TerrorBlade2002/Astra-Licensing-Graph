export function UnauthorizedPage() {
  return (
    <main className="empty-state">
      <h1>Access unavailable</h1>
      <p>
        Your account is authenticated but has not been assigned an Astra
        Licensing application role.
      </p>
    </main>
  );
}
