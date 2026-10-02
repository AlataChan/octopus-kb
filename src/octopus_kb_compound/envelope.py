"""Stage delivery parts and activate one revision at a time.

Checks run before any byte of the call is staged. The transition then runs
under a per-document lock, in this precedence:

1. invalid input → ``rejected:<reason>`` (nothing from this call is staged)
2. this revision is already active → ``active``
3. parts still missing → ``staged_incomplete``
4. staged aggregate differs from the manifest → ``rejected:status_mismatch``
5. approval missing or not valid for this revision → ``staged_awaiting_approval``
6. approval valid and the parent is the current active revision → ``activated``
7. approval valid and the parent differs → ``revision_conflict``

An ``activated`` commit fsyncs the rendered revision, then the activation
record, and only then the ``active`` pointer. Readers trust a record only
when it matches the pointer.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from octopus_kb_compound.approvals import (
    load_approval_keys,
    logical_document_id,
    manifest_digest,
    part_digest,
    verify_approval,
)
from octopus_kb_compound.jsoncanon import canonical_bytes
from octopus_kb_compound.models import PageMeta
from octopus_kb_compound.frontmatter import render_frontmatter
from octopus_kb_compound.resolver import VaultRootError, deployment_tenant, resolve_vault_id

_RANK = {"consistent_unverified": 0, "completed_partial": 1}
_SCHEMA_DIR = Path(__file__).resolve().parent / "_schemas"

# Tests set these. Production leaves them empty.
DURABILITY_LOG: list[str] = []
FAULT: str | None = None


class ActivationInterrupted(RuntimeError):
    """Raised when a test cuts the commit between durable steps."""


def ingest_envelope(
    vault_id: str,
    manifest: dict,
    parts: list,
    approval: dict | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(timezone.utc)
    reason = _invalid_reason(vault_id, manifest, parts)
    if reason is not None:
        revision = manifest.get("revision_id") if isinstance(manifest, dict) else None
        return {"status": f"rejected:{reason}", "revision_id": revision}

    config = resolve_vault_id(vault_id)
    logical = manifest["logical_document_id"]
    revision = manifest["revision_id"]
    with _document_lock(config.root, deployment_tenant(), vault_id, logical):
        for part in parts:
            _stage(config.root, logical, revision, part)
        pointer = _read_pointer(config.root, logical)
        if pointer == revision:
            return {"status": "active", "revision_id": revision}
        missing = _missing_indexes(config.root, logical, revision, manifest)
        if missing:
            return {
                "status": "staged_incomplete",
                "revision_id": revision,
                "missing_indexes": missing,
            }
        aggregate = _staged_aggregate(config.root, logical, revision, manifest)
        if aggregate != manifest["status"]:
            return {"status": "rejected:status_mismatch", "revision_id": revision}
        if not _approval_ok(approval, manifest, moment):
            return {"status": "staged_awaiting_approval", "revision_id": revision}
        parent = manifest["parent_revision_id"]
        if parent != pointer:
            return {"status": "revision_conflict", "revision_id": revision}
        _commit(config.root, manifest, approval, moment)
        return {"status": "activated", "revision_id": revision}


def _invalid_reason(vault_id: str, manifest: object, parts: object) -> str | None:
    if not isinstance(manifest, dict) or not isinstance(parts, list):
        return "malformed"
    if manifest.get("tenant") != deployment_tenant():
        return "tenant_mismatch"
    try:
        config = resolve_vault_id(vault_id)
    except VaultRootError as exc:
        return exc.reason
    if manifest.get("vault_id") != vault_id:
        return "vault_mismatch"
    if manifest.get("access_label") not in config.allowed_access_labels:
        return "access_label_forbidden"
    if _schema_error("revision-manifest.schema.json", manifest):
        return "malformed"
    if not _manifest_indexes_ok(manifest):
        return "part_index"
    expected_logical = logical_document_id(
        manifest["tenant"],
        manifest["vault_id"],
        manifest["placement"],
        manifest["access_label"],
    )
    if manifest.get("logical_document_id") != expected_logical:
        return "logical_document_mismatch"
    try:
        if manifest.get("revision_id") != manifest_digest(manifest):
            return "revision_mismatch"
    except (TypeError, ValueError):
        return "malformed"
    return _parts_reason(manifest, parts)


def _parts_reason(manifest: dict, parts: list) -> str | None:
    seen: set[str] = set()
    catalog = {
        (item["part_id"], item["index"], item["part_digest"]): item
        for item in manifest["parts"]
    }
    digests = [item["part_digest"] for item in manifest["parts"]]
    identities = [item["part_id"] for item in manifest["parts"]]
    if len(digests) != len(set(digests)) or len(identities) != len(set(identities)):
        return "duplicate_part"
    for part in parts:
        if not isinstance(part, dict):
            return "malformed"
        if _schema_error("delivery-envelope.schema.json", part):
            return "malformed"
        try:
            digest = part_digest(part)
        except (TypeError, ValueError):
            return "malformed"
        if digest != part.get("part_digest"):
            return "part_digest_mismatch"
        if (
            part.get("tenant") != manifest["tenant"]
            or part.get("logical_document_id") != manifest["logical_document_id"]
            or part.get("access_label") != manifest["access_label"]
        ):
            return "identity_mismatch"
        key = (part.get("part_id"), part.get("index"), digest)
        if key not in catalog:
            if digest in digests:
                return "identity_mismatch"
            return "extra_part"
        if digest in seen:
            return "duplicate_part"
        seen.add(digest)
    return None


def _manifest_indexes_ok(manifest: dict) -> bool:
    indexes = [part["index"] for part in manifest["parts"]]
    return indexes == list(range(len(indexes))) or sorted(indexes) == list(range(len(indexes)))


def _schema_error(name: str, instance: dict) -> bool:
    schema = json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))
    try:
        Draft202012Validator(schema).validate(instance)
    except ValidationError:
        return True
    return False


def _stage(root: Path, logical: str, revision: str, part: dict) -> None:
    digest = part["part_digest"]
    target = root / ".octopus-kb" / "staging" / logical / revision / f"{digest}.json"
    payload = canonical_bytes(part) + b"\n"
    if target.is_file() and _stage_is_complete(target, digest, payload):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    _publish_bytes(target, payload)


def _stage_is_complete(path: Path, digest: str, payload: bytes) -> bool:
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    return isinstance(parsed, dict) and parsed.get("part_digest") == digest and raw == payload


def _publish_bytes(path: Path, payload: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        tmp_path.unlink(missing_ok=True)


def _missing_indexes(root: Path, logical: str, revision: str, manifest: dict) -> list[int]:
    present = _staged_parts(root, logical, revision)
    got = {part["index"] for part in present}
    return [part["index"] for part in manifest["parts"] if part["index"] not in got]


def _staged_aggregate(root: Path, logical: str, revision: str, manifest: dict) -> str:
    by_index = {part["index"]: part for part in _staged_parts(root, logical, revision)}
    statuses = [by_index[part["index"]]["ledger_status"] for part in manifest["parts"]]
    return aggregate_status(statuses)


def aggregate_status(statuses: list[str]) -> str:
    """Maximum of the ranked order. Only the two accepted statuses participate."""
    if not statuses or any(status not in _RANK for status in statuses):
        raise ValueError("unranked_status")
    return max(statuses, key=_RANK.__getitem__)


def _staged_parts(root: Path, logical: str, revision: str) -> list[dict]:
    directory = root / ".octopus-kb" / "staging" / logical / revision
    if not directory.is_dir():
        return []
    loaded = []
    for path in sorted(directory.glob("*.json")):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(parsed, dict) and parsed.get("part_digest") == path.stem:
            loaded.append(parsed)
    return loaded


def _approval_ok(approval: dict | None, manifest: dict, now: datetime) -> bool:
    if not isinstance(approval, dict):
        return False
    verdict = verify_approval(
        approval,
        manifest,
        load_approval_keys(),
        tenant=deployment_tenant(),
        vault_id=manifest["vault_id"],
        access_label=manifest["access_label"],
        now=now,
    )
    return verdict.ok


def _commit(root: Path, manifest: dict, approval: dict, now: datetime) -> None:
    revision = manifest["revision_id"]
    logical = manifest["logical_document_id"]
    revision_dir = root / ".octopus-kb" / "revisions" / revision
    revision_dir.mkdir(parents=True, exist_ok=True)
    staged = {part["index"]: part for part in _staged_parts(root, logical, revision, )}
    bindings_parts = []
    for spec in manifest["parts"]:
        part = staged[spec["index"]]
        relative = _render_page(root, revision_dir, part)
        bindings_parts.append({
            "part_id": part["part_id"],
            "index": part["index"],
            "page": relative,
            "assets": [_asset_row(asset) for asset in part["assets"]],
            "relations": {
                "owners": part["relations"]["owners"],
                "spans": part["relations"]["spans"],
                "continues": part["relations"]["continues"],
            },
        })
    bindings = {
        "revision_id": revision,
        "logical_document_id": logical,
        "access_label": manifest["access_label"],
        "tenant": manifest["tenant"],
        "vault_id": manifest["vault_id"],
        "parts": bindings_parts,
    }
    _write_fsync(revision_dir / "bindings.json", canonical_bytes(bindings) + b"\n", "revision-file")
    _fsync_dir(revision_dir, "revision-dir")

    record = {
        "revision_id": revision,
        "approval_id": approval["approval_id"],
        "parent_revision_id": manifest["parent_revision_id"],
        "activated_at": _stamp(now),
        "ledger_status": manifest["status"],
        "logical_document_id": logical,
        "access_label": manifest["access_label"],
        "tenant": manifest["tenant"],
        "vault_id": manifest["vault_id"],
    }
    record_path = root / ".octopus-kb" / "activations" / f"{logical}.jsonl"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    _append_fsync(record_path, canonical_bytes(record) + b"\n", "activation-record")
    _checkpoint("before_pointer")

    active_dir = root / ".octopus-kb" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    temporary = active_dir / f".{logical}.tmp"
    _write_fsync(temporary, (revision + "\n").encode("utf-8"), "pointer-temp")
    _checkpoint("before_rename")
    os.replace(temporary, active_dir / logical)
    DURABILITY_LOG.append("pointer-rename")
    _fsync_dir(active_dir, "active-dir")


def _render_page(root: Path, revision_dir: Path, part: dict) -> str:
    title = str(part["part_id"])
    meta = PageMeta(
        title=title,
        page_type="raw_source",
        lang="en",
        role="raw_source",
        layer="source",
        summary=title,
        source_of_truth="canonical",
    )
    body = part["body"].rstrip()
    for asset in part["assets"]:
        ref = asset_reference(asset["asset_id"], asset["hash"])
        if ref not in body:
            body = f"{body}\n\n{ref}" if body else ref
    text = f"{render_frontmatter(meta)}\n{body}\n" if body else f"{render_frontmatter(meta)}\n"
    filename = f"{int(part['index']):04d}.md"
    _write_fsync(revision_dir / filename, text.encode("utf-8"), "revision-file")
    return (revision_dir / filename).resolve().relative_to(root.resolve()).as_posix()


def asset_reference(asset_id: str, digest: str) -> str:
    return f"octopus-asset://{asset_id}#sha256={digest}"


def _asset_row(asset: dict) -> dict:
    return {
        "asset_id": asset["asset_id"],
        "hash": asset["hash"],
        "owner_node_id": asset["owner_node_id"],
        "ref": asset_reference(asset["asset_id"], asset["hash"]),
    }


def _read_pointer(root: Path, logical: str) -> str | None:
    path = root / ".octopus-kb" / "active" / logical
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _write_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _write_fsync(path: Path, payload: bytes, event: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    DURABILITY_LOG.append(event)


def _append_fsync(path: Path, payload: bytes, event: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    DURABILITY_LOG.append(event)


def _fsync_dir(path: Path, event: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    DURABILITY_LOG.append(event)


def _checkpoint(name: str) -> None:
    if FAULT == name:
        raise ActivationInterrupted(name)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _document_lock(root: Path, tenant: str, vault_id: str, logical: str):
    import hashlib

    directory = root / ".octopus-kb" / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(f"{tenant}\0{vault_id}\0{logical}".encode("utf-8")).hexdigest()
    fd = os.open(directory / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

