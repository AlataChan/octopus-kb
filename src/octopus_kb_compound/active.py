"""One pinned view of ordinary pages plus each document's active revision.

Pointers are read once per call. Page bytes and provenance are taken from
that snapshot, so a later pointer change cannot mix old bytes with new
labels. Provenance comes from the activation record that matches the
pointer. Frontmatter is ignored. A page with no matching record is
``unledgered``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from octopus_kb_compound.models import PageRecord, VaultProfile
from octopus_kb_compound.resolver import VaultRootError, contained_leaf, is_managed_path
from octopus_kb_compound.vault import load_page, scan_markdown_files

UNLEDGERED = {
    "ledger_status": "unledgered",
    "revision_id": None,
    "logical_document_id": None,
    "access_label": None,
}

# Tests set this to change the vault after the pointers are captured.
AFTER_PIN = None


@dataclass
class VaultView:
    pages: list[PageRecord]
    provenance: dict[str, dict]
    text_by_path: dict[str, str]
    pointers: dict[str, str] = field(default_factory=dict)


def load_view(root: str | Path, profile: VaultProfile | None = None) -> VaultView:
    root_path = Path(root)
    if is_managed_path(root_path.resolve()):
        raise VaultRootError("managed_root")
    pointers = read_pointers(root_path)
    hook = AFTER_PIN
    if hook is not None:
        hook(root_path, dict(pointers))
    pages: list[PageRecord] = []
    provenance: dict[str, dict] = {}
    text_by_path: dict[str, str] = {}
    for page in scan_markdown_files(root_path, profile):
        try:
            text_by_path[page.path] = _read(root_path, root_path / page.path)
        except VaultRootError:
            continue
        pages.append(page)
        provenance[page.path] = dict(UNLEDGERED)
    for logical_id, revision_id in pointers.items():
        record = matching_record(root_path, logical_id, revision_id)
        if record is None:
            continue
        revision_dir = root_path / ".octopus-kb" / "revisions" / revision_id
        if not revision_dir.is_dir():
            continue
        try:
            contained_leaf(root_path, revision_dir)
        except VaultRootError:
            continue
        label = {
            "ledger_status": record["ledger_status"],
            "revision_id": revision_id,
            "logical_document_id": logical_id,
            "access_label": record["access_label"],
        }
        for path in sorted(revision_dir.glob("*.md")):
            try:
                page = load_page(path, root=root_path)
                text_by_path[page.path] = _read(root_path, path)
            except VaultRootError:
                continue
            pages.append(page)
            provenance[page.path] = dict(label)
    return VaultView(pages, provenance, text_by_path, dict(pointers))


def read_pointers(root: Path) -> dict[str, str]:
    active = root / ".octopus-kb" / "active"
    found: dict[str, str] = {}
    if not active.is_dir():
        return found
    for path in sorted(active.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        value = path.read_text(encoding="utf-8").strip()
        if value:
            found[path.name] = value
    return found


def matching_record(root: Path, logical_id: str, revision_id: str) -> dict | None:
    path = root / ".octopus-kb" / "activations" / f"{logical_id}.jsonl"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    match = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
        if record.get("revision_id") == revision_id:
            match = record
    return match


def _read(root: Path, path: Path) -> str:
    return contained_leaf(root, path).read_text(encoding="utf-8", errors="replace")
