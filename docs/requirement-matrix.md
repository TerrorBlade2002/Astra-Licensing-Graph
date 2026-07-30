# Advisory requirement matrix

Assessments pin a legal entity, an approved operating-profile version, an active
rule-set version, an effective date, and an input fingerprint. The evaluator
uses a constrained JSON condition language—never Python, SQL, or executable
expressions—and orders specific high-priority rules before broad rules.

Outcomes are advisory: `LIKELY_REQUIRED`, `POSSIBLY_REQUIRED`,
`LIKELY_NOT_REQUIRED`, `COUNSEL_REVIEW`, `OUT_OF_SCOPE`, or
`INSUFFICIENT_INFORMATION`. Each result records facts used, missing facts,
matched/conflicting rules, filing channels, source citations, freshness, and
human/counsel-review requirements.

Every result requires human review. “Not required” may require counsel by
configuration, stale authoritative sources can force counsel review, and
overrides preserve original outcome, authority, reason, source reference, and
validity dates. Approval does not create a license automatically.
