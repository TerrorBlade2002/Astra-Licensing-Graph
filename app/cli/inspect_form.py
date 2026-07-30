"""Inspect an AcroForm, controlled DOCX template, or flat form."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.forms.inspection import inspect_template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--format")
    args = parser.parse_args(argv)
    path = Path(args.file)
    result = inspect_template(path.read_bytes(), filename=path.name, declared_format=args.format)
    print(
        json.dumps(
            {
                "form_format": result.form_format,
                "detection_status": result.detection_status,
                "field_count": result.field_count,
                "notes": result.notes,
                "fields": [field.to_payload() for field in result.fields],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
