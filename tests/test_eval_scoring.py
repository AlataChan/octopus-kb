from octopus_kb_compound.eval.paths import PathResult
from octopus_kb_compound.eval.scoring import score
from octopus_kb_compound.eval.tasks import Task


def _mk(path_name, answer_json, sources=()):
    return PathResult(
        path_name=path_name,
        answer="",
        answer_json=answer_json,
        input_size_chars=0,
        sources=tuple(sources),
    )


def test_score_fact_lookup_exact_match():
    task = Task(
        id="t",
        type="fact_lookup",
        query="x",
        expected={"canonical_path": "wiki/concepts/Topic.md"},
    )
    result = _mk("octopus-kb", {"canonical": {"path": "wiki/concepts/Topic.md"}})
    assert score(task, result)["deterministic_score"] == 1.0


def test_score_fact_lookup_mismatch_is_zero():
    task = Task(
        id="t",
        type="fact_lookup",
        query="x",
        expected={"canonical_path": "wiki/concepts/Topic.md"},
    )
    result = _mk("octopus-kb", {"canonical": {"path": "wiki/concepts/Other.md"}})
    assert score(task, result)["deterministic_score"] == 0.0


def test_score_relationship_trace_f1():
    task = Task(
        id="t",
        type="relationship_trace",
        query="p",
        expected={"related_paths": ["a", "b"]},
    )
    result = _mk("octopus-kb", {"related_paths": ["a", "c"]})  # TP=1, FP=1, FN=1
    s = score(task, result)["deterministic_score"]
    # precision=0.5, recall=0.5, F1=0.5
    assert abs(s - 0.5) < 1e-6


def test_score_drift_detection_precision_recall():
    task = Task(
        id="t",
        type="drift_detection",
        query=None,
        expected={"stale_paths": ["a", "b"]},
    )
    result = _mk("octopus-kb", {"stale_paths": ["a"]})  # precision=1.0, recall=0.5
    s = score(task, result)["deterministic_score"]
    # average = 0.75
    assert abs(s - 0.75) < 1e-6
