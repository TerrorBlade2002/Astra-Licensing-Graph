"""Constrained rule DSL for requirement conditions.

The DSL is a small, closed set of JSON node types. It is *interpreted*, never
compiled or ``eval``-ed, so a malicious or mistaken rule can at worst produce a
wrong advisory answer — it can never execute code or reach the database.

Grammar
-------
Logical nodes::

    {"all": [<node>, ...]}      every child must hold
    {"any": [<node>, ...]}      at least one child must hold
    {"none": [<node>, ...]}     no child may hold
    {"not": <node>}             negation

Comparison nodes take a ``fact`` path and an operator::

    {"fact": "activities", "op": "contains", "value": "third_party_collection"}
    {"fact": "payment.accepts_direct", "op": "is_true"}
    {"fact": "employee_count", "op": "gte", "value": 5}
    {"fact": "debt_type", "op": "in", "value": ["consumer", "mixed"]}

Three-valued logic
------------------
A comparison returns ``TRUE``, ``FALSE``, or ``UNKNOWN``. ``UNKNOWN`` arises when
a referenced fact is absent or explicitly ``None`` — the difference between "we
know payments are not accepted" and "nobody has told us yet". That distinction is
the whole point: it drives ``INSUFFICIENT_INFORMATION`` and the missing-facts list
instead of silently treating unknown as false.

Kleene semantics apply: ``all`` is FALSE if any child is FALSE, else UNKNOWN if
any child is UNKNOWN, else TRUE. ``any`` is TRUE if any child is TRUE, else
UNKNOWN if any child is UNKNOWN, else FALSE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Final

MAX_DEPTH: Final = 12
MAX_NODES: Final = 400
# Each segment must start with a letter: rules address business facts, so a
# leading/trailing underscore or a dunder name is an authoring mistake. Fact
# lookup is pure dict indexing (never getattr), so this is hygiene rather than a
# sandbox boundary — the boundary is that the DSL is interpreted, not executed.
_FACT_PATH_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class Truth(Enum):
    """Three-valued result of evaluating a condition."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

    def __bool__(self) -> bool:  # pragma: no cover - guard against misuse
        raise TypeError(
            "Truth is three-valued; compare explicitly against Truth.TRUE/FALSE/UNKNOWN."
        )


LOGICAL_KEYS: Final = frozenset({"all", "any", "none", "not"})

#: Operators and their arity. ``needs_value`` marks operators requiring a
#: ``value`` key; presence/boolean operators do not take one.
OPERATORS: Final[dict[str, bool]] = {
    "eq": True,
    "ne": True,
    "in": True,
    "not_in": True,
    "contains": True,
    "not_contains": True,
    "contains_any": True,
    "contains_all": True,
    "gt": True,
    "gte": True,
    "lt": True,
    "lte": True,
    "matches": True,
    "before": True,
    "after": True,
    "is_true": False,
    "is_false": False,
    "is_present": False,
    "is_absent": False,
    "is_empty": False,
    "is_not_empty": False,
}


class RuleValidationError(ValueError):
    """A rule's ``conditions`` payload is not valid DSL."""


@dataclass(slots=True)
class EvaluationTrace:
    """Records which facts a rule actually consulted.

    Kept alongside the result so an explanation can state the facts used and the
    facts missing rather than asserting an unsupported conclusion.
    """

    facts_used: dict[str, Any] = field(default_factory=dict)
    missing_facts: list[str] = field(default_factory=list)

    def note_used(self, path: str, value: Any) -> None:
        self.facts_used[path] = value

    def note_missing(self, path: str) -> None:
        if path not in self.missing_facts:
            self.missing_facts.append(path)


def validate_conditions(node: Any, *, _depth: int = 0, _counter: list[int] | None = None) -> None:
    """Raise :class:`RuleValidationError` unless ``node`` is valid DSL.

    Bounds on depth and node count keep a pathological rule from turning
    evaluation into a denial of service against the API process.
    """
    counter = _counter if _counter is not None else [0]
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise RuleValidationError(f"Rule exceeds the maximum of {MAX_NODES} nodes.")
    if _depth > MAX_DEPTH:
        raise RuleValidationError(f"Rule nests deeper than {MAX_DEPTH} levels.")
    if not isinstance(node, dict):
        raise RuleValidationError(f"Condition nodes must be objects, got {type(node).__name__}.")
    if not node:
        raise RuleValidationError("Condition nodes must not be empty.")

    logical = LOGICAL_KEYS & node.keys()
    if logical:
        if len(node) != 1:
            raise RuleValidationError(
                f"Logical node must hold exactly one key, got {sorted(node)}."
            )
        key = next(iter(logical))
        child = node[key]
        if key == "not":
            validate_conditions(child, _depth=_depth + 1, _counter=counter)
            return
        if not isinstance(child, list) or not child:
            raise RuleValidationError(f"{key!r} requires a non-empty list of conditions.")
        for item in child:
            validate_conditions(item, _depth=_depth + 1, _counter=counter)
        return

    unknown = set(node) - {"fact", "op", "value", "case_sensitive"}
    if unknown:
        raise RuleValidationError(f"Unsupported condition keys: {sorted(unknown)}.")
    fact = node.get("fact")
    if not isinstance(fact, str) or not _FACT_PATH_PATTERN.match(fact):
        raise RuleValidationError(f"Fact paths must be lowercase dotted identifiers, got {fact!r}.")
    op = node.get("op")
    if op not in OPERATORS:
        raise RuleValidationError(f"Unsupported operator {op!r}; valid: {sorted(OPERATORS)}.")
    if OPERATORS[op] and "value" not in node:
        raise RuleValidationError(f"Operator {op!r} requires a 'value'.")
    if not OPERATORS[op] and "value" in node:
        raise RuleValidationError(f"Operator {op!r} must not carry a 'value'.")
    if op in ("in", "not_in", "contains_any", "contains_all") and not isinstance(
        node.get("value"), list
    ):
        raise RuleValidationError(f"Operator {op!r} requires a list 'value'.")
    if op == "matches":
        pattern = node.get("value")
        if not isinstance(pattern, str):
            raise RuleValidationError("Operator 'matches' requires a string pattern.")
        if len(pattern) > 200:
            raise RuleValidationError("Regex patterns are limited to 200 characters.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleValidationError(f"Invalid regex pattern: {exc}") from exc


def collect_fact_paths(node: Any, into: set[str] | None = None) -> set[str]:
    """Return every fact path a rule references, for missing-fact analysis."""
    paths = into if into is not None else set()
    if not isinstance(node, dict):
        return paths
    logical = LOGICAL_KEYS & node.keys()
    if logical:
        key = next(iter(logical))
        children = node[key] if key != "not" else [node[key]]
        if isinstance(children, list):
            for child in children:
                collect_fact_paths(child, paths)
        return paths
    fact = node.get("fact")
    if isinstance(fact, str):
        paths.add(fact)
    return paths


def resolve_fact(facts: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Look up a dotted path. Returns ``(found, value)``.

    ``found`` is False when any segment is absent, which is distinct from a
    present-but-null value; both map to UNKNOWN downstream but only a genuinely
    absent fact is worth asking a human about.
    """
    current: Any = facts
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False, None
    return True, current


def _as_comparable(value: Any) -> Any:
    """Coerce dates written as ISO strings so date operators work on JSON facts."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _compare(op: str, actual: Any, expected: Any, *, case_sensitive: bool) -> Truth:
    def norm(value: Any) -> Any:
        if not case_sensitive and isinstance(value, str):
            return value.casefold()
        return value

    def norm_seq(value: Any) -> list[Any]:
        items = value if isinstance(value, list | tuple | set) else [value]
        return [norm(item) for item in items]

    if op == "eq":
        return Truth.TRUE if norm(actual) == norm(expected) else Truth.FALSE
    if op == "ne":
        return Truth.TRUE if norm(actual) != norm(expected) else Truth.FALSE
    if op == "in":
        return Truth.TRUE if norm(actual) in norm_seq(expected) else Truth.FALSE
    if op == "not_in":
        return Truth.TRUE if norm(actual) not in norm_seq(expected) else Truth.FALSE
    if op in ("contains", "not_contains"):
        haystack = norm_seq(actual) if isinstance(actual, list | tuple | set) else norm(actual)
        needle = norm(expected)
        # Membership for sequences, substring for strings. Anything else (a
        # number, a dict) has no defined "contains" meaning, so stay UNKNOWN
        # rather than inventing an answer.
        if isinstance(haystack, list) or (isinstance(haystack, str) and isinstance(needle, str)):
            present = needle in haystack
        else:
            return Truth.UNKNOWN
        if op == "contains":
            return Truth.TRUE if present else Truth.FALSE
        return Truth.FALSE if present else Truth.TRUE
    if op in ("contains_any", "contains_all"):
        if not isinstance(actual, list | tuple | set):
            return Truth.UNKNOWN
        haystack = set(norm_seq(actual))
        wanted = set(norm_seq(expected))
        hit = bool(haystack & wanted) if op == "contains_any" else wanted <= haystack
        return Truth.TRUE if hit else Truth.FALSE
    if op in ("gt", "gte", "lt", "lte", "before", "after"):
        left, right = _as_comparable(actual), _as_comparable(expected)
        try:
            if op == "gt":
                result = left > right
            elif op == "gte":
                result = left >= right
            elif op == "lt":
                result = left < right
            elif op == "lte":
                result = left <= right
            elif op == "before":
                result = left < right
            else:
                result = left > right
        except TypeError:
            # Mismatched types are a rule-authoring problem, not a fact problem.
            return Truth.UNKNOWN
        return Truth.TRUE if result else Truth.FALSE
    if op == "matches":
        if not isinstance(actual, str):
            return Truth.UNKNOWN
        flags = 0 if case_sensitive else re.IGNORECASE
        return Truth.TRUE if re.search(str(expected), actual, flags) else Truth.FALSE
    return Truth.UNKNOWN


def evaluate(node: Any, facts: dict[str, Any], trace: EvaluationTrace | None = None) -> Truth:
    """Evaluate a validated DSL node against ``facts`` using Kleene logic."""
    tracker = trace if trace is not None else EvaluationTrace()

    logical = LOGICAL_KEYS & node.keys()
    if logical:
        key = next(iter(logical))
        if key == "not":
            inner = evaluate(node[key], facts, tracker)
            if inner is Truth.UNKNOWN:
                return Truth.UNKNOWN
            return Truth.FALSE if inner is Truth.TRUE else Truth.TRUE
        results = [evaluate(child, facts, tracker) for child in node[key]]
        if key == "all":
            if any(r is Truth.FALSE for r in results):
                return Truth.FALSE
            return Truth.UNKNOWN if any(r is Truth.UNKNOWN for r in results) else Truth.TRUE
        if key == "any":
            if any(r is Truth.TRUE for r in results):
                return Truth.TRUE
            return Truth.UNKNOWN if any(r is Truth.UNKNOWN for r in results) else Truth.FALSE
        # "none": true only when every child is definitively false.
        if any(r is Truth.TRUE for r in results):
            return Truth.FALSE
        return Truth.UNKNOWN if any(r is Truth.UNKNOWN for r in results) else Truth.TRUE

    path = str(node["fact"])
    op = str(node["op"])
    found, value = resolve_fact(facts, path)
    case_sensitive = bool(node.get("case_sensitive", False))

    # Presence operators are answerable even when the fact is absent.
    if op == "is_present":
        tracker.note_used(path, value if found else None)
        return Truth.TRUE if found and value is not None else Truth.FALSE
    if op == "is_absent":
        tracker.note_used(path, value if found else None)
        return Truth.TRUE if not found or value is None else Truth.FALSE

    if not found or value is None:
        tracker.note_missing(path)
        return Truth.UNKNOWN

    tracker.note_used(path, value)

    if op == "is_true":
        return Truth.TRUE if value is True else Truth.FALSE
    if op == "is_false":
        return Truth.TRUE if value is False else Truth.FALSE
    if op == "is_empty":
        return (
            Truth.TRUE
            if len(value) == 0
            else Truth.FALSE
            if hasattr(value, "__len__")
            else Truth.UNKNOWN
        )
    if op == "is_not_empty":
        if not hasattr(value, "__len__"):
            return Truth.UNKNOWN
        return Truth.TRUE if len(value) > 0 else Truth.FALSE

    return _compare(op, value, node.get("value"), case_sensitive=case_sensitive)


__all__ = [
    "MAX_DEPTH",
    "MAX_NODES",
    "OPERATORS",
    "EvaluationTrace",
    "RuleValidationError",
    "Truth",
    "collect_fact_paths",
    "evaluate",
    "resolve_fact",
    "validate_conditions",
]
