"""Document packet assembly.

A packet is an immutable snapshot of approved, in-date, correct-entity document
versions plus a manifest of hashes. Approval means "ready for the next
operational step" — it never transmits or submits anything.
"""
