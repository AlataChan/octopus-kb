def test_task_suite_has_expected_class_coverage():
    from octopus_kb_compound.eval.tasks import load_task_suite

    suite = load_task_suite("eval/tasks.yaml")
    counts = {"fact_lookup": 0, "relationship_trace": 0, "drift_detection": 0}
    for task in suite.tasks:
        counts[task.type] = counts.get(task.type, 0) + 1

    assert counts["fact_lookup"] >= 3
    assert counts["relationship_trace"] >= 3
    assert counts["drift_detection"] >= 3
    assert sum(counts.values()) >= 10
