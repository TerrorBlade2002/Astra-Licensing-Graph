"""Attachment filename safety.

Original filenames come from untrusted mail content. They are preserved
verbatim in the database (`original_filename`) but never used directly on
disk: stored names are sanitized, Unicode-normalized, and prefixed with the
attachment UUID for collision resistance.
"""

from __future__ import annotations

import re
import unicodedata

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_STORED_NAME_LENGTH = 120


def sanitize_filename(original: str | None, *, fallback: str = "attachment") -> str:
    """Return a filesystem-safe single-segment name derived from ``original``."""
    if not original:
        return fallback

    # Strip any path components regardless of separator convention.
    name = original.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name).strip()
    name = _INVALID_CHARS.sub("_", name)
    name = name.strip(". ")

    if not name or name in (".", ".."):
        return fallback

    stem, dot, ext = name.rpartition(".")
    base = stem if dot else name
    if base.lower() in _WINDOWS_RESERVED:
        name = f"_{name}"

    if len(name) > MAX_STORED_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            keep = MAX_STORED_NAME_LENGTH - len(ext) - 1
            name = f"{stem[:keep]}.{ext}"
        else:
            name = name[:MAX_STORED_NAME_LENGTH]
    return name


def stored_attachment_filename(attachment_uuid: str, original: str | None) -> str:
    """Collision-resistant on-disk name: '<uuid>_<safe-original>'."""
    return f"{attachment_uuid}_{sanitize_filename(original)}"
