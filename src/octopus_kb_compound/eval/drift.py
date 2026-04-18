"""Read-only drift detection helpers for eval runs."""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any


def compute_stale_pages(vault: Path | str) -> list[str]:
    """Return pages whose recorded raw-source SHA no longer matches the vault."""

    root = Path(vault)
    audit_dir = root / ".octopus-kb" / "audit"
    if not audit_dir.is_dir():
        return []

    stale: set[str] = set()
    for entry_path in sorted(audit_dir.glob("*.json")):
        entry = _load_audit_entry(entry_path)
        if entry is None:
            continue

        source = entry.get("source")
        applied_pages = entry.get("applied_pages")
        if not isinstance(source, dict) or not isinstance(applied_pages, list):
            warnings.warn(f"skipping audit entry with missing source/applied_pages: {entry_path}")
            continue

        source_path = source.get("path")
        recorded_sha = source.get("sha256")
        if not isinstance(source_path, str) or not isinstance(recorded_sha, str):
            warnings.warn(f"skipping audit entry with invalid source fields: {entry_path}")
            continue

        raw_path = root / source_path
        if not raw_path.is_file():
            continue

        current_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if current_sha != recorded_sha:
            stale.update(str(path) for path in applied_pages)

    return sorted(stale)


def _load_audit_entry(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.warn(f"skipping unreadable audit entry {path}: {exc}")
        return None
    if not isinstance(data, dict):
        warnings.warn(f"skipping non-object audit entry: {path}")
        return None
    return data
