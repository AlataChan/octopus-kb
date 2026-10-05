"""Lineage is owned by the knowledge base. Proposals do not carry it.

A parser-managed source is `.octopus-kb/part-propose/**` or
`.octopus-kb/revisions/**`. Status and authority come from the activation
record or the staged manifest, never from page frontmatter.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from octopus_kb_compound.active import activation_authority, matching_record
from octopus_kb_compound.approvals import (
    attestation_matches_activation,
    load_approval_keys,
    load_verifier_keys,
    part_digest,
    verify_approval,
)
from octopus_kb_compound.envelope import revision_page_text
from octopus_kb_compound.jsoncanon import canonical_bytes


MANAGED = ("part-propose", "revisions")


@dataclass(frozen=True)
class LineageDecision:
    allowed: bool
    reason: str
    authority: dict


@dataclass(frozen=True)
class TrustedPartBinding:
    """Staged part and the raw bytes that part authorizes."""

    part: dict
    raw_path: str
    raw_bytes: bytes


class PartBindingError(ValueError):
    """A caller part disagrees with the staged part it claims."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def managed_source(root: Path, candidate: str | Path) -> str | None:
    """Vault-relative path when the file is inside a parser-managed directory.

    Identity is the filesystem object, compared with ``os.path.samefile``
    and, for a hard link, the source inode. The returned path uses the
    on-disk names of those directories. A case variant, a ``./`` prefix, a
    ``..`` traversal, or a symlink alias of the same file all return that
    one path. A hard link to one managed file returns that file. A missing
    path that is still lexically inside a managed directory stays managed.
    Anything else returns None.
    """
    vault = Path(root).resolve()
    raw = Path(candidate)
    leaf = raw if raw.is_absolute() else vault / raw
    try:
        real = leaf.resolve(strict=True)
    except OSError:
        return _lexical_managed(vault, leaf)
    if not real.is_file():
        return None
    try:
        real.relative_to(vault)
    except ValueError:
        return None
    located = _managed_by_directory(vault, real)
    if located is not None:
        return located
    return _managed_by_inode(vault, real)


def is_parser_managed(root: Path, path: str | Path) -> bool:
    return managed_source(root, path) is not None


def canonicalize_sources(root: Path, proposal: dict) -> None:
    """Rewrite managed source paths to their on-disk vault-relative form."""
    source = proposal.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        canonical = managed_source(root, source["path"])
        if canonical is not None:
            source["path"] = canonical
    for operation in proposal.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        span = operation.get("source_span")
        if isinstance(span, dict) and isinstance(span.get("path"), str):
            canonical = managed_source(root, span["path"])
            if canonical is not None:
                span["path"] = canonical


def _managed_items(root: Path, proposal: dict) -> list[dict]:
    found = []
    for item in proposal_sources(proposal):
        canonical = managed_source(root, item["path"])
        if canonical is None:
            continue
        found.append({**item, "path": canonical})
    return found


def _managed_by_directory(vault: Path, real: Path) -> str | None:
    anchors = []
    for name in MANAGED:
        directory = vault / ".octopus-kb" / name
        if not directory.is_dir():
            continue
        try:
            anchors.append(directory.resolve())
        except OSError:
            continue
    current = real.parent
    matched = False
    while True:
        for anchor in anchors:
            try:
                if os.path.samefile(current, anchor):
                    matched = True
                    break
            except OSError:
                continue
        if matched or current == vault or current.parent == current:
            break
        try:
            current.relative_to(vault)
        except ValueError:
            break
        current = current.parent
    if not matched:
        return None
    return _on_disk_relative(vault, real)


def _lexical_managed(vault: Path, leaf: Path) -> str | None:
    """Keep a deleted parser-managed path inside the gate."""
    try:
        real = leaf.resolve(strict=False)
        rel = real.relative_to(vault)
    except (OSError, ValueError):
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == ".octopus-kb" and parts[1] in MANAGED:
        return rel.as_posix()
    return None


def _managed_by_inode(vault: Path, real: Path) -> str | None:
    """Return the managed file that is the same inode as ``real``.

    More than one managed name for that inode is ambiguous, so this returns
    None only when nothing matches. Ambiguous names stay managed by the
    first stable path; they do not become legacy input.
    """
    try:
        identity = real.stat()
    except OSError:
        return None
    matches: list[Path] = []
    for name in MANAGED:
        directory = vault / ".octopus-kb" / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                other = path.stat()
            except OSError:
                continue
            if other.st_dev == identity.st_dev and other.st_ino == identity.st_ino:
                matches.append(path)
    if not matches:
        return None
    chosen = min(matches, key=lambda item: item.as_posix())
    return _on_disk_relative(vault, chosen.resolve())


def _on_disk_relative(vault: Path, real: Path) -> str:
    chain = []
    current = real
    while True:
        try:
            if os.path.samefile(current, vault):
                break
        except OSError:
            break
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    names = []
    parent = vault
    for node in reversed(chain):
        name = node.name
        try:
            for entry in parent.iterdir():
                try:
                    if os.path.samefile(entry, node):
                        name = entry.name
                        break
                except OSError:
                    continue
        except OSError:
            pass
        names.append(name)
        parent = parent / name
    return "/".join(names)


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
    managed = _managed_items(root, proposal)
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
    canonical = managed_source(root, relpath)
    if canonical is None:
        return None
    if "/revisions/" in canonical:
        return _from_revision_page(root, canonical)
    return _from_part_file(root, canonical)


def assess_lineage(
    root: Path,
    proposal: dict,
    *,
    approval: dict | None,
    now: datetime | None = None,
) -> LineageDecision:
    moment = now or datetime.now(timezone.utc)
    managed = _managed_items(root, proposal)
    path = root / ".octopus-kb" / "lineage" / f"{proposal.get('id')}.json"
    if not managed:
        if path.is_file():
            return LineageDecision(False, "lineage_stale", {"kind": "missing"})
        return LineageDecision(True, "unledgered", {"kind": "unledgered"})
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


def trusted_part_binding(
    root: Path,
    relpath: str,
    *,
    proposed: dict | None = None,
) -> TrustedPartBinding | None:
    """Resolve the staged part that authorizes ``relpath``.

    A caller-supplied part is accepted only when a staged part exists for the
    claimed digest, the recomputed digest matches, and the canonical bytes are
    equal. The returned raw bytes come from that staged part. No staged part
    returns None so an unbound part can still be proposed.
    """
    canonical = managed_source(root, relpath)
    if canonical is None:
        return None
    part = _part_for_managed_path(root, canonical)
    if part is None:
        return None
    if proposed is not None:
        if not _proposed_matches_path(proposed, canonical):
            raise PartBindingError("part_digest_mismatch")
        if canonical_bytes(proposed) != canonical_bytes(part):
            raise PartBindingError("part_digest_mismatch")
    if "/revisions/" in canonical:
        raw = revision_page_text(part).encode("utf-8")
    else:
        raw = str(part.get("body") or "").encode("utf-8")
    return TrustedPartBinding(part=part, raw_path=canonical, raw_bytes=raw)


def _proposed_matches_path(part: dict, relpath: str) -> bool:
    if not isinstance(part, dict):
        return False
    try:
        digest = part_digest(part)
    except (TypeError, ValueError):
        return False
    claimed = part.get("part_digest")
    name = PurePosixPath(relpath).name.removesuffix(".md")
    return isinstance(claimed, str) and claimed == digest == name


def _part_for_managed_path(root: Path, canonical: str) -> dict | None:
    if "/revisions/" in canonical:
        parts = PurePosixPath(canonical).parts
        try:
            revision = parts[parts.index("revisions") + 1]
        except (ValueError, IndexError):
            return None
        record = _activation_for_revision(root, revision)
        if record is None:
            return None
        logical = str(record.get("logical_document_id") or "")
        return _staged_part(root, logical, revision, canonical)
    return _part_by_digest(root, PurePosixPath(canonical).name.removesuffix(".md"))


def _part_by_digest(root: Path, digest: str) -> dict | None:
    if not digest:
        return None
    staging = root / ".octopus-kb" / "staging"
    if not staging.is_dir():
        return None
    found: list[dict] = []
    for path in staging.glob(f"*/*/{digest}.json"):
        try:
            part = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(part, dict) and part.get("part_digest") == digest:
            found.append(part)
    if not found:
        return None
    first = canonical_bytes(found[0])
    if any(canonical_bytes(item) != first for item in found[1:]):
        return None
    return found[0]


def _entry(relpath: str, record: dict, part: dict, root: Path) -> dict | None:
    binding = trusted_part_binding(root, relpath)
    if binding is None or binding.part.get("part_digest") != part.get("part_digest"):
        return None
    try:
        actual = (root / relpath).read_bytes()
    except OSError:
        return None
    if actual != binding.raw_bytes:
        return None
    part = binding.part
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
