"""Deterministic eval path runners."""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octopus_kb_compound.cli import main as cli_main
from octopus_kb_compound.eval.drift import compute_stale_pages
from octopus_kb_compound.eval.tasks import Task


@dataclass(frozen=True)
class PathResult:
    path_name: str
    answer: str
    answer_json: dict[str, Any] | None
    input_size_chars: int
    sources: tuple[str, ...]


def run_grep_path(task: Task, corpus: Path | str) -> PathResult:
    """Run the pure-Python string-scan baseline for an eval task."""

    if task.type == "drift_detection":
        return PathResult(
            path_name="grep",
            answer="",
            answer_json={"stale_paths": []},
            input_size_chars=0,
            sources=(),
        )
    if task.query is None:
        raise ValueError(f"task {task.id} requires a query")

    root = Path(corpus)
    hits: list[str] = []
    sources: set[str] = set()
    for md_path in _markdown_files(root):
        relpath = md_path.relative_to(root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.find(task.query) >= 0:
                hits.append(f"{relpath}:{line_number}:{line}")
                sources.add(relpath)

    answer = "\n".join(hits)
    return PathResult(
        path_name="grep",
        answer=answer,
        answer_json=None,
        input_size_chars=len(answer),
        sources=tuple(sorted(sources)),
    )


def run_octopus_path(task: Task, corpus: Path | str) -> PathResult:
    """Run the deterministic octopus-kb path for an eval task."""

    root = Path(corpus)
    if task.type == "fact_lookup":
        if task.query is None:
            raise ValueError(f"task {task.id} requires a query")
        data = _run_cli_json(["lookup", task.query, "--vault", str(root), "--json"])
        canonical = data.get("canonical")
        answer = canonical.get("path", "") if isinstance(canonical, dict) else ""
        sources = _lookup_sources(data)
        return PathResult(
            path_name="octopus-kb",
            answer=answer,
            answer_json=data,
            input_size_chars=len(answer),
            sources=sources,
        )

    if task.type == "relationship_trace":
        if task.query is None:
            raise ValueError(f"task {task.id} requires a query")
        raw = _run_cli_json(["neighbors", task.query, "--vault", str(root), "--json"])
        related_paths = sorted(
            {
                item["path"]
                for item in raw.get("inbound", []) + raw.get("outbound", [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
        )
        answer = "\n".join(related_paths)
        return PathResult(
            path_name="octopus-kb",
            answer=answer,
            answer_json={"related_paths": related_paths},
            input_size_chars=len(answer),
            sources=tuple(related_paths),
        )

    if task.type == "drift_detection":
        stale_paths = compute_stale_pages(root)
        answer = "\n".join(stale_paths)
        return PathResult(
            path_name="octopus-kb",
            answer=answer,
            answer_json={"stale_paths": stale_paths},
            input_size_chars=len(answer),
            sources=tuple(stale_paths),
        )

    raise ValueError(f"unsupported eval task type: {task.type}")


def _markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(path)
    return files


def _run_cli_json(argv: list[str]) -> dict[str, Any]:
    buffer = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = buffer
    try:
        rc = cli_main(argv)
    finally:
        sys.stdout = original_stdout
    if rc != 0:
        raise RuntimeError(f"octopus-kb command failed with exit code {rc}: {' '.join(argv)}")
    data = json.loads(buffer.getvalue())
    if not isinstance(data, dict):
        raise RuntimeError("octopus-kb command did not return a JSON object")
    return data


def _lookup_sources(data: dict[str, Any]) -> tuple[str, ...]:
    sources: set[str] = set()
    canonical = data.get("canonical")
    if isinstance(canonical, dict) and isinstance(canonical.get("path"), str):
        sources.add(canonical["path"])
    for alias in data.get("aliases", []):
        if isinstance(alias, dict) and isinstance(alias.get("resolves_to"), str):
            sources.add(alias["resolves_to"])
    for collision in data.get("collisions", []):
        if isinstance(collision, str):
            sources.add(collision)
    return tuple(sorted(sources))
