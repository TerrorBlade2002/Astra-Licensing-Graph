"""Field worksheets for forms that cannot be mechanically filled.

A flat PDF or a portal form gets a **worksheet**, not a guessed overlay. The
worksheet is what an authorised user reads while typing into the real form or
portal themselves — the system never drives the portal.

Restricted values are never printed. The worksheet shows the masked display value
and tells the user where to retrieve the real one under audit.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from app.forms.enums import HUMAN_EXECUTION_FIELD_TYPES, FormFieldValueStatus
from app.information_registry.enums import Sensitivity

_MASKED_NOTICE = "[restricted - retrieve under audit]"


@dataclass(frozen=True, slots=True)
class WorksheetRow:
    """One line of the worksheet."""

    sort_order: int
    field_key: str
    label: str
    field_type: str
    required: bool
    status: str
    display_value: str | None
    source: str | None = None
    sensitivity: str = Sensitivity.INTERNAL.value
    page_number: int | None = None
    instructions: str | None = None
    owner: str | None = None

    @property
    def safe_value(self) -> str:
        """The only representation permitted in an exported worksheet."""
        if self.field_type in HUMAN_EXECUTION_FIELD_TYPES:
            return "*** SIGN / INITIAL / ATTEST IN PERSON ***"
        if self.status == FormFieldValueStatus.NEEDS_INFORMATION.value:
            return "*** MISSING - information request raised ***"
        if self.sensitivity in (Sensitivity.RESTRICTED.value, Sensitivity.HIGHLY_RESTRICTED.value):
            return self.display_value or _MASKED_NOTICE
        return self.display_value or ""


@dataclass(frozen=True, slots=True)
class WorksheetContext:
    form_name: str
    template_key: str
    template_version: int
    case_key: str
    legal_entity_name: str
    jurisdiction_name: str | None = None
    prepared_by_actor: str | None = None
    form_format: str | None = None
    generated_at: datetime | None = None


_HEADER_NOTE = (
    "This worksheet supports manual completion of a form or portal that cannot be "
    "filled mechanically. Nothing here is submitted automatically: no portal login, "
    "no browser automation, no filing, and no signature is performed by this system."
)


def build_rows_summary(rows: list[WorksheetRow]) -> dict[str, int]:
    return {
        "total": len(rows),
        "missing": sum(1 for r in rows if r.status == FormFieldValueStatus.NEEDS_INFORMATION.value),
        "signature_required": sum(1 for r in rows if r.field_type in HUMAN_EXECUTION_FIELD_TYPES),
        "needs_review": sum(1 for r in rows if r.status == FormFieldValueStatus.NEEDS_REVIEW.value),
        "restricted": sum(
            1
            for r in rows
            if r.sensitivity in (Sensitivity.RESTRICTED.value, Sensitivity.HIGHLY_RESTRICTED.value)
        ),
    }


def render_text_worksheet(context: WorksheetContext, rows: list[WorksheetRow]) -> str:
    """Human-readable worksheet."""
    moment = context.generated_at or datetime.now(tz=UTC)
    summary = build_rows_summary(rows)
    lines = [
        "FORM FIELD WORKSHEET",
        "=" * 78,
        f"Form:         {context.form_name}",
        f"Template:     {context.template_key} v{context.template_version}"
        f" ({context.form_format or 'unknown format'})",
        f"Case:         {context.case_key}",
        f"Legal entity: {context.legal_entity_name}",
        f"Jurisdiction: {context.jurisdiction_name or 'n/a'}",
        f"Prepared by:  {context.prepared_by_actor or 'system'}",
        f"Generated:    {moment.isoformat()}",
        "",
        _HEADER_NOTE,
        "",
        f"Fields: {summary['total']} total | {summary['missing']} missing | "
        f"{summary['signature_required']} require personal execution | "
        f"{summary['needs_review']} need review",
        "=" * 78,
        "",
    ]
    for row in sorted(rows, key=lambda r: (r.sort_order, r.field_key)):
        flag = "REQUIRED" if row.required else "optional"
        page = f" (page {row.page_number})" if row.page_number else ""
        lines.append(f"[{row.sort_order:>4}] {row.label}{page}  -- {flag}")
        lines.append(f"        field:  {row.field_key} ({row.field_type})")
        lines.append(f"        value:  {row.safe_value}")
        lines.append(f"        status: {row.status}")
        if row.source:
            lines.append(f"        source: {row.source}")
        if row.owner:
            lines.append(f"        owner:  {row.owner}")
        if row.instructions:
            lines.append(f"        note:   {row.instructions}")
        lines.append("")
    lines += ["=" * 78, "End of worksheet."]
    return "\n".join(line for line in lines if line is not None)


def render_csv_worksheet(context: WorksheetContext, rows: list[WorksheetRow]) -> str:
    """CSV worksheet. Values pass through the same masking as the text version."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "sort_order",
            "field_key",
            "label",
            "field_type",
            "required",
            "status",
            "value",
            "source",
            "sensitivity",
            "page_number",
            "owner",
            "instructions",
        ]
    )
    for row in sorted(rows, key=lambda r: (r.sort_order, r.field_key)):
        writer.writerow(
            [
                row.sort_order,
                row.field_key,
                row.label,
                row.field_type,
                "yes" if row.required else "no",
                row.status,
                # Guard against CSV formula injection: a leading =, +, -, or @ is
                # prefixed so a spreadsheet treats it as text.
                _csv_safe(row.safe_value),
                row.source or "",
                row.sensitivity,
                row.page_number or "",
                row.owner or "",
                row.instructions or "",
            ]
        )
    return buffer.getvalue()


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection in exported worksheets."""
    text = value or ""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def render_pdf_worksheet(context: WorksheetContext, rows: list[WorksheetRow]) -> bytes:
    """Printable PDF worksheet.

    A generated document, not an overlay on the original: nothing is drawn onto the
    regulator's form at guessed coordinates.
    """
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise RuntimeError("reportlab is required to render PDF worksheets.") from exc

    moment = context.generated_at or datetime.now(tz=UTC)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    _page_width, height = LETTER
    margin = 0.75 * inch
    y = height - margin

    def line(text: str, *, size: int = 9, bold: bool = False, indent: float = 0.0) -> None:
        nonlocal y
        if y < margin + 0.5 * inch:
            pdf.showPage()
            y = height - margin
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(margin + indent, y, text[:110])
        y -= size + 3

    pdf.setTitle(f"Field worksheet - {context.form_name}")
    line("FORM FIELD WORKSHEET", size=14, bold=True)
    y -= 4
    line(f"Form: {context.form_name}", bold=True)
    line(f"Template: {context.template_key} v{context.template_version}")
    line(f"Case: {context.case_key}    Legal entity: {context.legal_entity_name}")
    line(f"Jurisdiction: {context.jurisdiction_name or 'n/a'}")
    line(f"Prepared by: {context.prepared_by_actor or 'system'}    Generated: {moment.isoformat()}")
    y -= 6
    for chunk in _wrap(_HEADER_NOTE, 105):
        line(chunk, size=8)
    y -= 6
    summary = build_rows_summary(rows)
    line(
        f"{summary['total']} fields | {summary['missing']} missing | "
        f"{summary['signature_required']} personal execution | "
        f"{summary['needs_review']} need review",
        bold=True,
    )
    y -= 8

    for row in sorted(rows, key=lambda r: (r.sort_order, r.field_key)):
        flag = "REQUIRED" if row.required else "optional"
        page = f" (page {row.page_number})" if row.page_number else ""
        line(f"{row.label}{page}  [{flag}]", bold=True)
        line(f"field: {row.field_key} ({row.field_type})", size=8, indent=12)
        line(f"value: {row.safe_value}", size=9, indent=12)
        line(f"status: {row.status}   source: {row.source or 'n/a'}", size=8, indent=12)
        if row.instructions:
            for chunk in _wrap(f"note: {row.instructions}", 95):
                line(chunk, size=8, indent=12)
        y -= 2

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


__all__ = [
    "WorksheetContext",
    "WorksheetRow",
    "build_rows_summary",
    "render_csv_worksheet",
    "render_pdf_worksheet",
    "render_text_worksheet",
]
