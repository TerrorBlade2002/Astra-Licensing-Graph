# Requirement source governance

Sources distinguish official primary material, official guidance, approved
counsel, vendor operational instructions, internal policy, and unverified
material. Vendor instructions can guide a case but are not automatically legal
authority.

Every content version is SHA-256 identified. Changed content creates a
`PENDING_REVIEW` snapshot, keeps the last approved snapshot active, and notifies
the owner. Approval advances the source pointer but never edits active rules; a
new rule-set version and regression review are required.

Manual snapshots must reference the controlled URI holding the exact immutable
bytes; inline text alone is rejected. The public-source worker stores both the
bounded raw response and, when safely decodable, a separate extracted-text
artifact. Neither an upload-session URL nor a temporary download URL is stored.

Public fetching is disabled unless explicitly enabled and host-allow-listed.
Authenticated NMLS/state portals, login paths, CAPTCHA bypass, and search-snippet
inference are prohibited. NMLS new-application and annual-renewal exports are
separate source types and may identify both NMLS and outside-NMLS work.

Freshness windows are configurable by source. Stale evidence is visible in
assessment results and may force counsel review.
