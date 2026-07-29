"""Signals suspicious evidence without following or deleting it."""

import re

_SIGNALS = (
    re.compile(r"(?i)ignore (?:all |the )?(?:previous|system) instructions"),
    re.compile(r"(?i)reveal (?:the )?(?:system prompt|instructions|secret)"),
    re.compile(r"(?i)(?:call|use) (?:a )?(?:tool|web search|file search)"),
    re.compile(r"(?i)you are (?:now|an? )"),
)


def detect_prompt_injection(value: str) -> list[str]:
    return [
        f"prompt_injection_signal:{index + 1}"
        for index, pattern in enumerate(_SIGNALS)
        if pattern.search(value)
    ]
