export function ValidationMessagePanel({
  messages,
}: {
  messages: Array<Record<string, unknown>>;
}) {
  return (
    <section className="panel">
      <h2>Portal validation</h2>
      {messages.length === 0 ? (
        <p className="muted">No captured validation messages.</p>
      ) : (
        <ul className="finding-list">
          {messages.map((message, index) => (
            <li key={`${String(message.code)}-${index}`}>
              <strong>{String(message.code ?? "PORTAL_VALIDATION")}</strong>
              <span>{String(message.message ?? "")}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
