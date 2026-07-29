"""Packet manifests, cover sheets, and ZIP archives.

The manifest is the packet's identity. It is built from a canonical, sorted
structure and hashed, so:

* re-running a build over unchanged documents yields the same ``manifest_sha256``;
* swapping any document, version, or hash changes it, which is how a stale or
  tampered packet is detected;
* an approved packet can be verified later without trusting the archive bytes.

Filenames are sanitised aggressively. Regulator-facing archives must not carry
path separators, control characters, reserved Windows device names, or unicode
tricks that could escape an extraction directory.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MAX_FILENAME_LENGTH = 120

# Reserved device names on Windows; a file called "CON.pdf" is unusable there.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COLLAPSE = re.compile(r"[\s_]+")


def safe_filename(name: str, *, fallback: str = "document", extension: str | None = None) -> str:
    """Produce a filename safe for ZIP entries and downstream extraction.

    Strips directory traversal, control characters, and reserved names; normalises
    unicode so visually-identical names cannot collide unpredictably.
    """
    normalized = unicodedata.normalize("NFKD", name or "")
    # Take the basename only: defeats "../" and absolute paths.
    normalized = normalized.replace("\\", "/").split("/")[-1]
    cleaned = _UNSAFE_CHARS.sub("", normalized).strip().strip(".")
    cleaned = _COLLAPSE.sub(" ", cleaned).strip()

    stem, dot, ext = cleaned.rpartition(".")
    if dot and 1 <= len(ext) <= 8 and ext.isalnum():
        base, suffix = stem, f".{ext.lower()}"
    else:
        base, suffix = cleaned, ""
    if extension:
        suffix = extension if extension.startswith(".") else f".{extension}"

    if not base:
        base = fallback
    if base.upper() in _RESERVED_NAMES:
        base = f"{base}-file"

    allowed = int(MAX_FILENAME_LENGTH) - len(suffix)
    return f"{base[:allowed].strip() or fallback}{suffix}"


def unique_filename(name: str, taken: set[str]) -> str:
    """Disambiguate a filename within one archive without overwriting."""
    if name not in taken:
        taken.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    base, suffix = (stem, f".{ext}") if dot else (name, "")
    for index in range(2, 1000):
        candidate = f"{base} ({index}){suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    fallback = f"{base}-{len(taken)}{suffix}"
    taken.add(fallback)
    return fallback


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One included document, pinned by version and hash."""

    item_key: str
    document_type: str
    document_id: str
    document_version_id: str | None
    filename_in_archive: str
    source_filename: str
    sha256: str | None
    size_bytes: int
    effective_date: str | None
    expiry_date: str | None
    sort_order: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "document_type": self.document_type,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "filename_in_archive": self.filename_in_archive,
            "source_filename": self.source_filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "effective_date": self.effective_date,
            "expiry_date": self.expiry_date,
            "sort_order": self.sort_order,
        }


@dataclass(frozen=True, slots=True)
class OmittedEntry:
    item_key: str
    document_type: str
    required: bool
    status: str
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "document_type": self.document_type,
            "required": self.required,
            "status": self.status,
            "reason": self.reason,
        }


def build_manifest(
    *,
    packet_key: str,
    version: int,
    case_key: str,
    legal_entity_name: str,
    jurisdiction_name: str | None,
    license_type_name: str | None,
    template_key: str | None,
    included: list[ManifestEntry],
    omitted: list[OmittedEntry],
    missing: list[OmittedEntry],
    created_by_actor: str | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the manifest payload in canonical order."""
    moment = generated_at or datetime.now(tz=UTC)
    return {
        "manifest_version": 1,
        "packet_key": packet_key,
        "packet_version": version,
        "case_key": case_key,
        "legal_entity": legal_entity_name,
        "jurisdiction": jurisdiction_name,
        "license_type": license_type_name,
        "packet_template_key": template_key,
        "generated_at": moment.isoformat(),
        "created_by_actor": created_by_actor,
        "included_count": len(included),
        "omitted_count": len(omitted),
        "missing_count": len(missing),
        "included": [
            entry.to_payload()
            for entry in sorted(included, key=lambda e: (e.sort_order, e.item_key))
        ],
        "omitted": [entry.to_payload() for entry in sorted(omitted, key=lambda e: e.item_key)],
        "missing": [entry.to_payload() for entry in sorted(missing, key=lambda e: e.item_key)],
    }


def manifest_sha256(manifest: dict[str, Any]) -> str:
    """Hash the manifest excluding volatile fields.

    ``generated_at`` is excluded on purpose: two builds of the same documents should
    be recognisably identical, and a timestamp would make every rebuild look like a
    change.
    """
    import json

    stable = {key: value for key, value in manifest.items() if key != "generated_at"}
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_cover_sheet(manifest: dict[str, Any], *, instructions: str | None = None) -> str:
    """Plain-text cover sheet. Text keeps the packet portable and diff-able."""
    lines = [
        "DOCUMENT PACKET COVER SHEET",
        "=" * 60,
        f"Packet:         {manifest['packet_key']} (version {manifest['packet_version']})",
        f"Case:           {manifest['case_key']}",
        f"Legal entity:   {manifest['legal_entity']}",
        f"Jurisdiction:   {manifest.get('jurisdiction') or 'Not jurisdiction-specific'}",
        f"Licence type:   {manifest.get('license_type') or 'Not licence-specific'}",
        f"Template:       {manifest.get('packet_template_key') or 'Ad hoc'}",
        f"Generated:      {manifest['generated_at']}",
        f"Prepared by:    {manifest.get('created_by_actor') or 'system'}",
        "",
        "This packet was assembled from approved, in-date documents belonging to the",
        "legal entity named above. Approval of this packet confirms readiness for the",
        "next operational step only; it does not transmit or submit anything.",
        "",
        f"INCLUDED DOCUMENTS ({manifest['included_count']})",
        "-" * 60,
    ]
    for entry in manifest["included"]:
        lines.append(f"{entry['sort_order']:>4}. {entry['filename_in_archive']}")
        lines.append(f"      type:    {entry['document_type']}")
        lines.append(f"      sha256:  {entry['sha256']}")
        if entry.get("effective_date") or entry.get("expiry_date"):
            lines.append(
                f"      valid:   {entry.get('effective_date') or 'n/a'}"
                f" to {entry.get('expiry_date') or 'no expiry'}"
            )
    if manifest["missing_count"]:
        lines += ["", f"MISSING ITEMS ({manifest['missing_count']})", "-" * 60]
        for entry in manifest["missing"]:
            flag = "REQUIRED" if entry["required"] else "optional"
            lines.append(f"  - [{flag}] {entry['document_type']} ({entry['item_key']})")
            lines.append(f"      reason: {entry['reason']}")
    if manifest["omitted_count"]:
        lines += ["", f"DELIBERATELY OMITTED ({manifest['omitted_count']})", "-" * 60]
        for entry in manifest["omitted"]:
            lines.append(f"  - {entry['document_type']} ({entry['item_key']}): {entry['reason']}")
    if instructions:
        lines += ["", "INSTRUCTIONS", "-" * 60, instructions]
    lines += ["", "=" * 60, "End of cover sheet."]
    return "\n".join(lines)


def build_archive(
    *,
    manifest: dict[str, Any],
    files: dict[str, bytes],
    cover_sheet: str | None = None,
    include_manifest_json: bool = True,
) -> tuple[bytes, str]:
    """Build a deterministic ZIP archive. Returns ``(bytes, sha256)``.

    Entries use a fixed timestamp and sorted order so the same inputs produce
    byte-identical archives — which makes the archive hash a meaningful integrity
    check rather than a build-time artefact.
    """
    import json

    buffer = io.BytesIO()
    fixed_time = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if cover_sheet is not None:
            info = zipfile.ZipInfo("00-cover-sheet.txt", date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, cover_sheet.encode("utf-8"))
        if include_manifest_json:
            info = zipfile.ZipInfo("00-manifest.json", date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8"),
            )
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    raw = buffer.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def verify_entry_hash(content: bytes, expected_sha256: str | None) -> bool:
    """Confirm retrieved bytes match the hash recorded in the catalogue."""
    if not expected_sha256:
        return False
    return hashlib.sha256(content).hexdigest() == expected_sha256.lower()


__all__ = [
    "MAX_FILENAME_LENGTH",
    "ManifestEntry",
    "OmittedEntry",
    "build_archive",
    "build_manifest",
    "manifest_sha256",
    "render_cover_sheet",
    "safe_filename",
    "unique_filename",
    "verify_entry_hash",
]
