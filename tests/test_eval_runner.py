import json
from pathlib import Path


def test_run_suite_writes_per_task_json_and_summary(tmp_path):
    from octopus_kb_compound.eval.runner import run_suite

    tasks_file = Path("eval/tasks.yaml")  # committed by prior task
    out = tmp_path / "run"
    summary = run_suite(tasks_file, out)
    assert (out / "fact-001.json").exists()
    assert (out / "summary.md").exists()
    data = json.loads((out / "fact-001.json").read_text(encoding="utf-8"))
    assert "results" in data and isinstance(data["results"], list)
    for r in data["results"]:
        assert "path_name" in r and "deterministic_score" in r
        assert "latency_ms" not in r, "latency must not appear in deterministic JSON"
        assert "latency_ns" not in r


def test_run_suite_produces_separate_metrics_file_with_latency_ms(tmp_path):
    from octopus_kb_compound.eval.runner import run_suite

    tasks_file = Path("eval/tasks.yaml")
    out = tmp_path / "run2"
    run_suite(tasks_file, out)
    metrics = out / "fact-001.metrics.json"
    assert metrics.exists()
    data = json.loads(metrics.read_text(encoding="utf-8"))
    assert "metrics" in data and isinstance(data["metrics"], list)
    assert any("latency_ms" in entry for entry in data["metrics"])
