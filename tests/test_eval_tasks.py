import pytest


def test_load_task_suite_parses_valid_yaml(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text(
        """
version: 1
corpus: eval/corpora/small-vault
tasks:
  - id: f1
    type: fact_lookup
    query: "RAG Ops"
    expected:
      canonical_path: "wiki/concepts/RAG Operations.md"
""",
        encoding="utf-8",
    )
    from octopus_kb_compound.eval.tasks import load_task_suite

    suite = load_task_suite(path)
    assert len(suite.tasks) == 1
    assert suite.tasks[0].type == "fact_lookup"


def test_load_task_suite_rejects_unknown_type(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text(
        """
version: 1
corpus: eval/corpora/small-vault
tasks:
  - id: x
    type: nonsense
    query: "q"
    expected: {}
""",
        encoding="utf-8",
    )
    from octopus_kb_compound.eval.tasks import EvalError, load_task_suite

    with pytest.raises(EvalError):
        load_task_suite(path)


def test_load_task_suite_rejects_missing_required_field(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text(
        """
version: 1
tasks:
  - id: x
    type: fact_lookup
    expected: {}
""",
        encoding="utf-8",
    )
    from octopus_kb_compound.eval.tasks import EvalError, load_task_suite

    with pytest.raises(EvalError):
        load_task_suite(path)
