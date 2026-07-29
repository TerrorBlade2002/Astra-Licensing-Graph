"""Email normalization that preserves line boundaries and separates quoted history."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CleanBody:
    current_message: str
    quoted_history: str


_QUOTE_MARKERS = (
    re.compile(r"^On .+wrote:\s*$", re.I),
    re.compile(r"^From:\s+.+$", re.I),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}$", re.I),
)
_BANNER = re.compile(r"(?is)(confidentiality notice|this (?:email|message) is intended only).*$")
_TAG = re.compile(r"<[^>]+>")


def normalize_body(
    body: str | None, *, max_chars: int = 40_000, quoted_max_chars: int = 5_000
) -> CleanBody:
    value = unicodedata.normalize("NFKC", html.unescape(body or ""))
    value = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", value)
    value = _TAG.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    quote_at = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith(">") or any(p.match(line) for p in _QUOTE_MARKERS)
        ),
        len(lines),
    )
    current = "\n".join(lines[:quote_at])
    quoted = "\n".join(lines[quote_at:])
    current = _BANNER.sub("", current)
    current = re.sub(r"\n{3,}", "\n\n", current).strip()[:max_chars]
    return CleanBody(current_message=current, quoted_history=quoted.strip()[:quoted_max_chars])
