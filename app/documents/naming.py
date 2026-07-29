"""Canonical, non-sensitive governed-document filename generation."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import PurePath

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _component(value: str | None, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or fallback)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("", _CONTROL.sub("", ascii_value)).strip(". ")
    return cleaned or fallback


def trusted_extension(filename: str, allowed_extensions: list[str]) -> str:
    name = PurePath(filename.replace("\\", "/")).name
    extension = PurePath(name).suffix.lower()
    allowed = {
        item.lower() if item.startswith(".") else f".{item.lower()}" for item in allowed_extensions
    }
    if extension not in allowed:
        raise ValueError("The file extension is not approved for governed storage.")
    return extension


def canonical_filename(
    *,
    legal_entity: str | None,
    jurisdiction: str | None,
    document_type: str,
    relevant_date: date | None,
    short_id: str,
    original_filename: str,
    allowed_extensions: list[str],
    max_length: int = 180,
) -> str:
    extension = trusted_extension(original_filename, allowed_extensions)
    parts = [
        _component(legal_entity, "Astra"),
        _component(jurisdiction, "MultiState"),
        _component(document_type.title().replace("_", ""), "Document"),
        relevant_date.isoformat() if relevant_date else "Undated",
        _component(short_id, "000000")[:12],
    ]
    stem = "_".join(parts).strip(". ")
    if stem.upper() in _RESERVED:
        stem = f"Document_{stem}"
    available = max(1, max_length - len(extension))
    return f"{stem[:available].rstrip('. ')}{extension}"


def sanitize_download_filename(filename: str, max_length: int = 180) -> str:
    base = PurePath(filename.replace("\\", "/")).name
    base = unicodedata.normalize("NFKC", _CONTROL.sub("", base)).strip(". ")
    base = re.sub(r"[\"/:*?<>|]+", "_", base)
    if not base:
        base = "document"
    stem = PurePath(base).stem
    if stem.upper() in _RESERVED:
        base = f"document_{base}"
    return base[:max_length].rstrip(". ")
