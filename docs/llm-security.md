# Optional model security

Model enrichment is off by default and requires all of `AI_CLASSIFICATION_ENABLED`, `AI_EXTERNAL_PROVIDER_APPROVED`, a provider/model/key, and `AI_DATA_POLICY_ACKNOWLEDGED`. The adapter uses the Responses API with strict JSON Schema and `store=false`; it omits tools, web/file search, background mode, conversation state, and uploads.

Only sanitized subject/current body, deterministic hints, filenames/MIME types, approved document metadata, taxonomy, and schema are sent. SSNs, payment numbers, account identifiers, and credential-like strings are redacted; full quoted history and binaries are excluded. Email instructions are explicitly untrusted. Prompt-injection signals are recorded for review, never executed.

Responses are rejected on refusal, incomplete status, timeout/HTTP failure, invalid schema/taxonomy, invented filenames, or untraceable quotes. Request IDs, token counts, and latency are stored; API keys never enter frontend assets, prompts, logs, database rows, or audit payloads.
