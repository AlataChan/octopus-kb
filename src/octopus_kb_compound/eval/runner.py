"""Eval suite runner orchestration."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from octopus_kb_compound.eval.paths import PathResult, run_grep_path, run_octopus_path
from octopus_kb_compound.eval.scoring import score
from octopus_kb_compound.eval.tasks import Task, load_task_suite


@dataclass
class TaskRun:
    task: Task
    results: list[dict[str, Any]]
    metrics: list[dict[str, Any]]


def run_suite(tasks_file: Path | str, out_dir: Path | str) -> dict[str, Any]:
    """Run both eval paths over every task and write deterministic artifacts."""

    task_path = Path(tasks_file)
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)

    suite = load_task_suite(task_path)
    task_jsons: list[Path] = []
    metrics_jsons: list[Path] = []
    runs: list[TaskRun] = []

    for task in suite.tasks:
        run = _run_task(task, suite.corpus)
        runs.append(run)

        task_json = output / f"{task.id}.json"
        _write_json(
            task_json,
            {
                "task_id": task.id,
                "task_type": task.type,
                "results": run.results,
            },
        )
        task_jsons.append(task_json)

        metrics_json = output / f"{task.id}.metrics.json"
        _write_json(metrics_json, {"task_id": task.id, "metrics": run.metrics})
        metrics_jsons.append(metrics_json)

    summary_path = output / "summary.md"
    summary_path.write_text(
        render_summary(
            task_path,
            suite.corpus,
            runs,
        ),
        encoding="utf-8",
    )

    return {
        "summary_path": summary_path,
        "task_jsons": task_jsons,
        "metrics_jsons": metrics_jsons,
    }


def render_summary(
    tasks_file: Path | str,
    corpus: Path | str,
    runs: list[TaskRun],
) -> str:
    """Render the frozen deterministic markdown summary."""

    lines = [
        "# Eval Summary",
        "",
        f"Tasks file: {_display_path(Path(tasks_file))}",
        f"Corpus: {_display_path(Path(corpus))}",
        f"Total tasks: {len(runs)}",
        "",
        "| task_id | type | grep_score | octopus_score |",
        "|---|---|---|---|",
    ]
    for run in sorted(runs, key=lambda item: item.task.id):
        scores = {
            result["path_name"]: float(result["deterministic_score"])
            for result in run.results
        }
        lines.append(
            f"| {run.task.id} | {run.task.type} | "
            f"{scores.get('grep', 0.0):.2f} | {scores.get('octopus-kb', 0.0):.2f} |"
        )
    return "\n".join(lines) + "\n"


def _run_task(task: Task, corpus: Path) -> TaskRun:
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for runner in (run_grep_path, run_octopus_path):
        path_result, latency_ms = _time_path(runner, task, corpus)
        scored = score(task, path_result)
        results.append(_result_to_dict(path_result, scored))
        metrics.append({"path_name": path_result.path_name, "latency_ms": latency_ms})
    return TaskRun(task=task, results=results, metrics=metrics)


def _time_path(
    runner: Callable[[Task, Path], PathResult],
    task: Task,
    corpus: Path,
) -> tuple[PathResult, float]:
    start_ns = time.perf_counter_ns()
    result = runner(task, corpus)
    end_ns = time.perf_counter_ns()
    return result, round((end_ns - start_ns) / 1_000_000, 3)


def _result_to_dict(
    result: PathResult,
    scored: dict[str, float | str],
) -> dict[str, Any]:
    return {
        "path_name": result.path_name,
        "answer": result.answer,
        "answer_json": result.answer_json,
        "input_size_chars": result.input_size_chars,
        "sources": sorted(result.sources),
        "deterministic_score": scored["deterministic_score"],
        "rationale": scored["rationale"],
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
