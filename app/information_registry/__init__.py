"""Reusable company-information registry.

Stores approved answers to recurring licensing questions so the same question is
never chased twice. Values are legal-entity scoped, versioned, owned, approved,
and freshness-controlled. Restricted values are encrypted at rest, masked in
lists, never logged, and never sent to an AI model.
"""
