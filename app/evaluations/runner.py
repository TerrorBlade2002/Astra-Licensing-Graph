"""Offline deterministic evaluation; provider use is intentionally opt-in elsewhere."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.classification.deterministic import ClassificationInput, DeterministicClassifier


@dataclass(frozen=True)
class EvaluationReport:
    dataset_version: str
    examples: int
    exact_matches: int
    email_type_accuracy: float
    vendor_accuracy: float
    state_precision: float
    state_recall: float

    def as_dict(self) -> dict[str, object]:
        return self.__dict__


def evaluate(path: Path) -> EvaluationReport:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    exact = type_correct = vendor_correct = state_tp = predicted_states = expected_states = 0
    version = "unknown"
    classifier = DeterministicClassifier()
    for row in rows:
        version = row.get("dataset_version", version)
        predicted = classifier.classify(ClassificationInput(**row["input"])).output
        expected: dict[str, Any] = row["expected"]
        type_correct += predicted.email_type == expected["email_type"]
        vendor_correct += predicted.vendor == expected.get("vendor")
        predicted_set, expected_set = set(predicted.states), set(expected.get("states", []))
        state_tp += len(predicted_set & expected_set)
        predicted_states += len(predicted_set)
        expected_states += len(expected_set)
        exact += (
            predicted.email_type == expected["email_type"]
            and predicted.vendor == expected.get("vendor")
            and predicted_set == expected_set
        )
    total = len(rows)
    return EvaluationReport(
        dataset_version=version,
        examples=total,
        exact_matches=exact,
        email_type_accuracy=type_correct / total if total else 0,
        vendor_accuracy=vendor_correct / total if total else 0,
        state_precision=state_tp / predicted_states if predicted_states else 0,
        state_recall=state_tp / expected_states if expected_states else 0,
    )
