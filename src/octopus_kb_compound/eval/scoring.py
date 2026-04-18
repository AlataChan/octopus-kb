"""Deterministic scoring for eval path outputs."""

from __future__ import annotations

from typing import Any

from octopus_kb_compound.eval.paths import PathResult
from octopus_kb_compound.eval.tasks import Task


def score(task: Task, result: PathResult) -> dict[str, float | str]:
    """Return a deterministic score and short rationale for a task/path result."""

    if task.type == "fact_lookup":
        return _score_fact_lookup(task, result)
    if task.type == "relationship_trace":
        return _score_relationship_trace(task, result)
    if task.type == "drift_detection":
        return _score_drift_detection(task, result)
    return {"deterministic_score": 0.0, "rationale": f"unsupported task type: {task.type}"}


def _score_fact_lookup(task: Task, result: PathResult) -> dict[str, float | str]:
    expected = str(task.expected.get("canonical_path", ""))
    actual = ""
    if isinstance(result.answer_json, dict):
        canonical = result.answer_json.get("canonical")
        if isinstance(canonical, dict):
            actual = str(canonical.get("path", ""))
    else:
        actual = expected if expected in result.sources else ""

    matched = actual == expected and bool(expected)
    return {
        "deterministic_score": 1.0 if matched else 0.0,
        "rationale": f"expected {expected}, got {actual or '<none>'}",
    }


def _score_relationship_trace(task: Task, result: PathResult) -> dict[str, float | str]:
    expected = set(_string_list(task.expected.get("related_paths", [])))
    if isinstance(result.answer_json, dict):
        predicted = set(_string_list(result.answer_json.get("related_paths", [])))
    else:
        predicted = set(result.sources)
    f1 = _f1(predicted, expected)
    return {
        "deterministic_score": f1,
        "rationale": f"predicted={len(predicted)} expected={len(expected)} f1={f1:.3f}",
    }


def _score_drift_detection(task: Task, result: PathResult) -> dict[str, float | str]:
    expected = set(_string_list(task.expected.get("stale_paths", [])))
    predicted = set()
    if isinstance(result.answer_json, dict):
        predicted = set(_string_list(result.answer_json.get("stale_paths", [])))

    if not predicted and not expected:
        precision = recall = 1.0
    else:
        true_positive = len(predicted & expected)
        precision = true_positive / len(predicted) if predicted else 0.0
        recall = true_positive / len(expected) if expected else 0.0
    deterministic_score = (precision + recall) / 2
    return {
        "deterministic_score": deterministic_score,
        "rationale": f"precision={precision:.3f} recall={recall:.3f}",
    }


def _f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted or not expected:
        return 0.0
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted)
    recall = true_positive / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
