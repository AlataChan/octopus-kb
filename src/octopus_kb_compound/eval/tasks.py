"""Loader for YAML eval task suites."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class EvalError(Exception):
    """Raised when an eval task suite cannot be loaded or validated."""


@dataclass(frozen=True)
class Task:
    id: str
    type: str
    query: str | None
    expected: dict[str, Any]


@dataclass(frozen=True)
class TaskSuite:
    version: int
    corpus: Path
    tasks: list[Task]


def load_task_suite(path: Path | str) -> TaskSuite:
    """Load and validate a v1 eval task suite YAML file."""

    task_path = Path(path)
    try:
        data = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvalError(f"failed to read task suite: {task_path}") from exc
    except yaml.YAMLError as exc:
        raise EvalError(f"invalid YAML in task suite: {task_path}") from exc

    if data is None:
        data = {}

    _validate_task_suite(data)

    return TaskSuite(
        version=int(data["version"]),
        corpus=Path(data["corpus"]),
        tasks=[
            Task(
                id=str(task["id"]),
                type=str(task["type"]),
                query=task.get("query"),
                expected=dict(task["expected"]),
            )
            for task in data["tasks"]
        ],
    )


def _validate_task_suite(data: Any) -> None:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path)
        prefix = f"{path}: " if path else ""
        raise EvalError(f"{prefix}{first.message}")


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "schemas" / "eval" / "tasks-v1.json"
