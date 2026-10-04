"""Lineage is owned by the knowledge base. Proposals do not carry it.

A parser-managed source is `.octopus-kb/part-propose/**` or
`.octopus-kb/revisions/**`. Status and authority come from the activation
record or the staged manifest, never from page frontmatter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from octopus_kb_compound.active import activation_authority, matching_record
from octopus_kb_compound.approvals import (
    attestation_matches_activation,
    load_approval_keys,
    load_verifier_keys,
    verify_approval,
)


MANAGED = ("part-propose", "revisions")


@dataclass(frozen=True)
class LineageDecision:
    allowed: bool
    reason: str
    authority: dict


def is_parser_managed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if ".octopus-kb" not in parts:
        return False
    index = parts.index(".octopus-kb")
    return len(parts) > index + 1 and parts[index + 1] in MANAGED


def proposal_sources(proposal: dict) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()

    def add(path: object, digest: object) -> None:
        if not isinstance(path, str) or not path or path in seen:
            return
        seen.add(path)
        found.append({"path": path, "sha256": digest if isinstance(digest, str) else ""})

    source = proposal.get("source") if isinstance(proposal.get("source"), dict) else {}
    if source.get("kind") == "raw_file":
        add(source.get("path"), source.get("sha256"))
    for operation in proposal.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        span = operation.get("source_span")
        if isinstance(span, dict):
            add(span.get("path"), span.get("sha256"))
    return found


def write_lineage(root: Path, proposal: dict) -> Path | None:
    """Write lineage when every managed source resolves. Otherwise write nothing."""
    managed = [item for item in proposal_sources(proposal) if is_parser_managed(item["path"])]
    if not managed:
        return None
    sources = []
    for item in managed:
        resolved = resolve_source(root, item["path"])
        if resolved is None:
            return None
        sources.append(resolved)
    payload = {
        "schema_version": "lineage/0.1.0",
        "proposal_id": str(proposal.get("id") or ""),
        "sources": sources,
    }
    directory = root / ".octopus-kb" / "lineage"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{payload['proposal_id']}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def resolve_source(root: Path, relpath: str) -> dict | None:
    if not is_parser_managed(relpath):
        return None
    if "/revisions/" in relpath:
        return _from_revision_page(root, relpath)
    return _from_part_file(root, relpath)


def assess_lineage(
    root: Path,
    proposal: dict,
    *,
    approval: dict | None,
    now: datetime | None = None,
) -> LineageDecision:
    moment = now or datetime.now(timezone.utc)
    managed = [item for item in proposal_sources(proposal) if is_parser_managed(item["path"])]
    if not managed:
        return LineageDecision(True, "unledgered", {"kind": "unledgered"})
    path = root / ".octopus-kb" / "lineage" / f"{proposal.get('id')}.json"
    if not path.is_file():
        return LineageDecision(False, "lineage_missing", {"kind": "missing"})
    try:
        lineage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return LineageDecision(False, "lineage_mismatch", {"kind": "missing"})
    if lineage.get("proposal_id") != proposal.get("id"):
        return LineageDecision(False, "lineage_mismatch", {"kind": "missing"})
    entries = {item.get("raw_path"): item for item in lineage.get("sources") or [] if isinstance(item, dict)}
    authority = {"kind": "unledgered"}
    for item in managed:
        entry = entries.get(item["path"])
        if entry is None:
            return LineageDecision(False, "lineage_missing", {"kind": "missing"})
        try:
            current = file_sha256(root, item["path"])
        except OSError:
            return LineageDecision(False, "lineage_stale", entry.get("authority") or {"kind": "missing"})
        if current != entry.get("raw_sha256"):
            return LineageDecision(False, "lineage_stale", entry.get("authority") or {"kind": "missing"})
        if item["sha256"] and item["sha256"] != entry.get("raw_sha256"):
            return LineageDecision(False, "lineage_mismatch", entry.get("authority") or {"kind": "missing"})
        trusted = resolve_source(root, item["path"])
        if trusted is None:
            return LineageDecision(False, "lineage_stale", entry.get("authority") or {"kind": "missing"})
        if trusted["revision_id"] != entry.get("revision_id"):
            return LineageDecision(False, "lineage_stale", entry.get("authority") or {"kind": "missing"})
        if not _same_binding(trusted, entry):
            return LineageDecision(False, "lineage_mismatch", entry.get("authority") or {"kind": "missing"})
        decision = _authority_ok(root, entry, approval, moment)
        if not decision.allowed:
            return decision
        authority = decision.authority
    return LineageDecision(True, "ok", authority)


def file_sha256(root: Path, relpath: str) -> str:
    path = root / relpath
    if "/revisions/" in relpath:
        data = path.read_text(encoding="utf-8", errors="replace").encode("utf-8")
    else:
        data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def record_apply(root: Path, proposal_id: str, authority: dict, outcome: str) -> None:
    directory = root / ".octopus-kb"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "apply-log.jsonl"
    line = json.dumps(
        {"proposal_id": proposal_id, "authority": authority, "outcome": outcome},
        sort_keys=True,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _from_revision_page(root: Path, relpath: str) -> dict | None:
    parts = PurePosixPath(relpath).parts
    revision = parts[parts.index("revisions") + 1]
    record = _activation_for_revision(root, revision)
    if record is None:
        return None
    logical = str(record.get("logical_document_id") or "")
    part = _staged_part(root, logical, revision, relpath)
    if part is None:
        return None
    return _entry(relpath, record, part, root)


def _from_part_file(root: Path, relpath: str) -> dict | None:
    digest = PurePosixPath(relpath).name.removesuffix(".md")
    staging = root / ".octopus-kb" / "staging"
    if not staging.is_dir():
        return None
    for path in staging.glob(f"*/*/{digest}.json"):
        try:
            part = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(part, dict) or part.get("part_digest") != digest:
            continue
        revision = path.parent.name
        logical = path.parent.parent.name
        record = _activation_for_revision(root, revision)
        if record is None or record.get("logical_document_id") != logical:
            record = {
                "logical_document_id": logical,
                "revision_id": revision,
                "ledger_status": part.get("ledger_status"),
                "tenant": part.get("tenant"),
                "vault_id": part.get("vault_id") or "",
                "access_label": part.get("access_label"),
                "authority": {"kind": "approval", "approval_id": None},
            }
        return _entry(relpath, record, part, root)
    return None


def _entry(relpath: str, record: dict, part: dict, root: Path) -> dict:
    authority = record.get("authority")
    if not isinstance(authority, dict):
        authority = activation_authority(record)
    return {
        "logical_document_id": record.get("logical_document_id"),
        "revision_id": record.get("revision_id"),
        "part_digest": part.get("part_digest"),
        "part_status": record.get("ledger_status"),
        "destination": {
            "tenant": record.get("tenant"),
            "vault_id": record.get("vault_id"),
            "access_label": record.get("access_label"),
        },
        "authority": authority,
        "raw_path": relpath,
        "raw_sha256": file_sha256(root, relpath),
    }


def _activation_for_revision(root: Path, revision: str) -> dict | None:
    active = root / ".octopus-kb" / "active"
    if not active.is_dir():
        return None
    for pointer in sorted(active.iterdir()):
        if not pointer.is_file() or pointer.name.startswith("."):
            continue
        if pointer.read_text(encoding="utf-8").strip() != revision:
            continue
        return matching_record(root, pointer.name, revision)
    return None


def _staged_part(root: Path, logical: str, revision: str, relpath: str) -> dict | None:
    bindings_path = root / ".octopus-kb" / "revisions" / revision / "bindings.json"
    if not bindings_path.is_file():
        return None
    try:
        bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    index = None
    for part in bindings.get("parts") or []:
        if part.get("page") == relpath:
            index = part.get("index")
    if index is None:
        return None
    directory = root / ".octopus-kb" / "staging" / logical / revision
    if not directory.is_dir():
        return None
    for path in directory.glob("*.json"):
        try:
            part = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(part, dict) and part.get("index") == index:
            return part
    return None


def _same_binding(trusted: dict, entry: dict) -> bool:
    return (
        trusted.get("logical_document_id") == entry.get("logical_document_id")
        and trusted.get("part_digest") == entry.get("part_digest")
        and trusted.get("part_status") == entry.get("part_status")
        and trusted.get("destination") == entry.get("destination")
        and trusted.get("authority") == entry.get("authority")
    )


def _authority_ok(root: Path, entry: dict, approval: dict | None, now: datetime) -> LineageDecision:
    status = entry.get("part_status")
    authority = entry.get("authority") if isinstance(entry.get("authority"), dict) else {}
    destination = entry.get("destination") or {}
    if status == "succeeded" and authority.get("kind") == "attestation":
        attestation = _read_attestation(root, str(authority.get("attestation_id") or ""))
        if attestation is None:
            return LineageDecision(False, "attestation_invalid", authority)
        try:
            keys = load_verifier_keys()
        except Exception as exc:
            return LineageDecision(False, "attestation_invalid", authority)
        verdict = attestation_matches_activation(
            attestation,
            revision_id=str(entry.get("revision_id") or ""),
            logical_document_id=str(entry.get("logical_document_id") or ""),
            tenant=str(destination.get("tenant") or ""),
            vault_id=str(destination.get("vault_id") or ""),
            access_label=str(destination.get("access_label") or ""),
            trusted_keys=keys,
            now=now,
        )
        if not verdict.ok:
            return LineageDecision(False, verdict.reason, authority)
        return LineageDecision(True, "ok", authority)
    if not isinstance(approval, dict):
        return LineageDecision(False, "approval_required", authority)
    try:
        keys = load_approval_keys()
    except Exception:
        return LineageDecision(False, "approval_required", authority)
    verdict = verify_approval(
        approval,
        {
            "tenant": destination.get("tenant"),
            "vault_id": destination.get("vault_id"),
            "access_label": destination.get("access_label"),
            "status": status,
        },
        keys,
        tenant=str(destination.get("tenant") or ""),
        vault_id=str(destination.get("vault_id") or ""),
        access_label=str(destination.get("access_label") or ""),
        now=now,
        expected_subject=str(entry.get("revision_id") or ""),
    )
    if not verdict.ok:
        return LineageDecision(False, verdict.reason, authority)
    return LineageDecision(
        True,
        "ok",
        {"kind": "approval", "approval_id": approval.get("approval_id")},
    )


def _read_attestation(root: Path, attestation_id: str) -> dict | None:
    if not attestation_id:
        return None
    path = root / ".octopus-kb" / "attestations" / f"{attestation_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
