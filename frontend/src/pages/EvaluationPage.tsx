import { RoleGuard } from "../auth/RoleGuard";
export function EvaluationPage() {
  return (
    <RoleGuard role="Licensing.Manager">
      <main>
        <div className="page-title">
          <div>
            <span className="eyebrow">Regression control</span>
            <h1>Classification evaluation</h1>
            <p>
              Run synthetic, redacted datasets before changing active rules or
              prompts.
            </p>
          </div>
          <button className="primary">Run evaluation</button>
        </div>
        <div className="metric-grid">
          <article>
            <small>Dataset</small>
            <strong className="text-metric">v1</strong>
            <span>synthetic baseline</span>
          </article>
          <article>
            <small>Exact match</small>
            <strong>—</strong>
            <span>no run selected</span>
          </article>
          <article>
            <small>Correction rate</small>
            <strong>—</strong>
            <span>awaiting results</span>
          </article>
          <article>
            <small>External cost</small>
            <strong>$0</strong>
            <span>provider disabled</span>
          </article>
        </div>
        <section className="panel evaluation-empty">
          <div className="empty-icon">△</div>
          <h2>Evaluation infrastructure is ready</h2>
          <p>
            Use the backend evaluation CLI with a versioned JSONL dataset. Live
            providers are never called unless both approval flags are enabled.
          </p>
          <code>
            python -m app.cli.classification_eval --dataset
            tests/fixtures/classification_eval_v1.jsonl
          </code>
        </section>
      </main>
    </RoleGuard>
  );
}
