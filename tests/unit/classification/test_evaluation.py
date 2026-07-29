from pathlib import Path

from app.evaluations.runner import evaluate


def test_versioned_offline_evaluation_dataset() -> None:
    report = evaluate(Path("tests/fixtures/classification_eval_v1.jsonl"))
    assert report.dataset_version == "v1"
    assert report.examples == 2
    assert report.email_type_accuracy == 1
    assert report.state_recall == 1
