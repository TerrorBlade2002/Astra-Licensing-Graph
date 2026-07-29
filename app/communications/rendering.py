"""Sandboxed deterministic response-template rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jinja2 import StrictUndefined, meta, nodes
from jinja2.sandbox import SandboxedEnvironment

FORBIDDEN_NODES = (
    nodes.Call,
    nodes.Getattr,
    nodes.Getitem,
    nodes.Import,
    nodes.FromImport,
    nodes.Include,
)
PLACEHOLDER = re.compile(r"({{.*?}}|{%.*?%}|\[TODO\]|<insert\s+value>)", re.I | re.S)


@dataclass(frozen=True)
class RenderedResponse:
    subject: str
    body_text: str
    body_html: str | None


class ResponseTemplateRenderer:
    def __init__(self) -> None:
        self.environment = self._environment(autoescape=False)
        self.html_environment = self._environment(autoescape=True)

    @staticmethod
    def _environment(*, autoescape: bool) -> SandboxedEnvironment:
        environment = SandboxedEnvironment(
            undefined=StrictUndefined, autoescape=autoescape, enable_async=False
        )
        environment.globals.clear()
        environment.filters.clear()
        environment.tests.clear()
        return environment

    def validate_template(self, source: str, allowed_variables: list[str]) -> None:
        syntax = self.environment.parse(source)
        if any(next(syntax.find_all(node_type), None) is not None for node_type in FORBIDDEN_NODES):
            raise ValueError("Template contains forbidden traversal, call, or import syntax.")
        undeclared = meta.find_undeclared_variables(syntax)
        unexpected = undeclared - set(allowed_variables)
        if unexpected:
            raise ValueError(f"Template uses non-allowlisted variables: {sorted(unexpected)}")

    def render(
        self,
        *,
        subject_template: str | None,
        text_template: str,
        html_template: str | None,
        allowed_variables: list[str],
        values: dict[str, Any],
    ) -> RenderedResponse:
        for source in (subject_template or "", text_template, html_template or ""):
            self.validate_template(source, allowed_variables)
        unknown = set(values) - set(allowed_variables)
        if unknown:
            raise ValueError(f"Unapproved template values supplied: {sorted(unknown)}")
        subject = self.environment.from_string(
            subject_template or "Re: licensing correspondence"
        ).render(**values)
        text_body = self.environment.from_string(text_template).render(**values)
        html_body = (
            self.html_environment.from_string(html_template).render(**values)
            if html_template
            else None
        )
        for rendered in (subject, text_body, html_body or ""):
            if PLACEHOLDER.search(rendered):
                raise ValueError("Rendered response contains an unresolved placeholder.")
        return RenderedResponse(
            subject.strip(), text_body.strip(), html_body.strip() if html_body else None
        )
