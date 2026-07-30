# Pre-submission verification

A pre-submission snapshot is an immutable, canonical hash of the exact run inputs and observed portal state:

- legal entity, filing type, case, license, form, and packet identifiers;
- every material field's approved and entered fingerprints;
- exact document and version identifiers, expected hashes, portal names, sizes, and verification status;
- portal validation messages, fee summary, and blocking discrepancies;
- pinned portal review and adapter versions.

A snapshot with a missing, mismatched, human-only-unresolved, or unverified value cannot be approved. The creator cannot approve their own snapshot. Only the latest exact snapshot can be approved.

Any field edit, source refresh, document change, validation recapture, assignment change, adapter change, review expiry, attestation change, or fee change invalidates approval. Final-submit handoff creation recomputes the governance boundary and requires the current approved snapshot plus completed human attestation, signature, and payment evidence.

