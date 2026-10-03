"""Proposal schema validation and append-only proposal storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import jsonschema


class ProposalCollisionError(ValueError):
    """Raised when a proposal id would overwrite an existing proposal file."""


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "llm" / "proposal.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def validate_proposal_dict(data: dict[str, Any]) -> list[str]:
    """Return JSON Schema validation error messages for a proposal dictionary."""

    validator = jsonschema.Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [error.message for error in errors]


def proposal_id_from_key(interpretation_key: str) -> str:
    """Identity is the interpretation key. A model-supplied id is not used."""

    if not interpretation_key or "/" in interpretation_key or "\\" in interpretation_key:
        raise ValueError("proposal id source is not a safe interpretation key")
    return interpretation_key


def proposal_bytes(proposal: dict[str, Any]) -> bytes:
    """Canonical on-disk bytes for a proposal body."""

    return (json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode("utf-8")


def save_proposal(proposal: dict[str, Any], vault_root: Path | str) -> Path:
    """Atomically write an append-only proposal file under `.octopus-kb/proposals/`.

    An identical stored body is returned as-is. A different body under the
    same id is a collision and is never overwritten.
    """

    proposal_id = str(proposal["id"])
    if "/" in proposal_id or "\\" in proposal_id:
        raise ValueError("proposal id must not contain path separators")

    root = Path(vault_root)
    proposal_dir = root / ".octopus-kb" / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    target = proposal_dir / f"{proposal_id}.json"
    payload = proposal_bytes(proposal)
    if _identical_or_collision(target, payload, proposal_id):
        return target

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{proposal_id}.",
        suffix=".tmp",
        dir=proposal_dir,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if _identical_or_collision(target, payload, proposal_id):
            return target
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return target


def _identical_or_collision(target: Path, payload: bytes, proposal_id: str) -> bool:
    """Return True when the stored file is already this body."""

    if not target.exists():
        return False
    if target.read_bytes() == payload:
        return True
    raise ProposalCollisionError(f"proposal id already exists: {proposal_id}")


def load_proposal(path: Path | str) -> dict[str, Any]:
    """Load a proposal JSON file."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
