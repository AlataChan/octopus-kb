from pathlib import Path


def _corpus():
    return Path(__file__).resolve().parent.parent / "eval" / "corpora" / "small-vault"


def test_grep_path_returns_matches_for_fact_lookup():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import PathResult, run_grep_path

    task = Task(
        id="x",
        type="fact_lookup",
        query="RAG Ops",
        expected={"canonical_path": "wiki/concepts/RAG Operations.md"},
    )
    result = run_grep_path(task, _corpus())
    assert isinstance(result, PathResult)
    assert result.path_name == "grep"
    assert "RAG Ops" in result.answer
    assert result.sources
    # Must be sorted for determinism.
    assert list(result.sources) == sorted(result.sources)


def test_octopus_path_fact_lookup_returns_canonical():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_octopus_path

    task = Task(
        id="x",
        type="fact_lookup",
        query="RAG Ops",
        expected={"canonical_path": "wiki/concepts/RAG Operations.md"},
    )
    result = run_octopus_path(task, _corpus())
    assert result.path_name == "octopus-kb"
    assert result.answer_json is not None
    assert result.answer_json["canonical"]["path"] == "wiki/concepts/RAG Operations.md"


def test_octopus_path_drift_detection_returns_engineered_stale():
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_octopus_path

    task = Task(
        id="d",
        type="drift_detection",
        query=None,
        expected={"stale_paths": ["wiki/concepts/RAG Operations.md"]},
    )
    result = run_octopus_path(task, _corpus())
    assert result.answer_json is not None
    assert "wiki/concepts/RAG Operations.md" in result.answer_json["stale_paths"]


def test_grep_path_is_bit_identical_across_invocations():
    """Pure-Python grep must be deterministic regardless of host platform."""
    from octopus_kb_compound.eval.tasks import Task
    from octopus_kb_compound.eval.paths import run_grep_path

    task = Task(
        id="x",
        type="fact_lookup",
        query="RAG Ops",
        expected={"canonical_path": "wiki/concepts/RAG Operations.md"},
    )
    a = run_grep_path(task, _corpus())
    b = run_grep_path(task, _corpus())
    assert a == b
