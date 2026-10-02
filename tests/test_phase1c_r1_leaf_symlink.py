"""Escaping file symlinks must not return outside bytes through vault reads."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from octopus_kb_compound.active import load_view
from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
from octopus_kb_compound.llm import ChatClient, LLMError
from octopus_kb_compound.neighbors import compute_neighbors
from octopus_kb_compound.propose import ProposeRuntimeError, propose_from_raw
from octopus_kb_compound.resolver import VaultRootError
from octopus_kb_compound.vault import load_page, scan_markdown_files

SECRET = "UNIQUE_OUTSIDE_SECRET_BYTES"
MCP_ROOT = Path(__file__).resolve().parents[1] / "mcp"


def _page(title: str, body: str, role: str = "note") -> str:
    return "\n".join([
        "---",
        f'title: "{title}"',
        "type: note",
        "lang: en",
        f"role: {role}",
        "aliases:",
        f'  - "{title}"',
        "---",
        "",
        body,
        "",
    ])


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    wiki = root / "wiki"
    raw = root / "raw"
    wiki.mkdir(parents=True)
    raw.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text(
        _page(SECRET, f"Source {SECRET}", role="concept"),
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(_page("Inside Note", "inside body stays"), encoding="utf-8")
    (wiki / "alias.md").symlink_to(wiki / "index.md")
    (wiki / "link.md").symlink_to(secret)
    (raw / "source.md").write_text(_page("Source", "ordinary raw"), encoding="utf-8")

    logical = "logical-one"
    revision = "rev-one"
    managed = root / ".octopus-kb"
    (managed / "active").mkdir(parents=True)
    (managed / "active" / logical).write_text(revision + "\n", encoding="utf-8")
    (managed / "activations").mkdir()
    (managed / "activations" / f"{logical}.jsonl").write_text(
        json.dumps({
            "revision_id": revision,
            "ledger_status": "consistent_unverified",
            "access_label": "internal",
        }) + "\n",
        encoding="utf-8",
    )
    revision_dir = managed / "revisions" / revision
    revision_dir.mkdir(parents=True)
    (revision_dir / "kept.md").write_text(
        _page("Managed Inside", "managed inside stays"),
        encoding="utf-8",
    )
    (revision_dir / "leaked.md").symlink_to(secret)

    monkeypatch.delenv("OCTOPUS_KB_MODEL_POLICY", raising=False)
    monkeypatch.delenv("OCTOPUS_KB_CONFIG", raising=False)
    monkeypatch.setenv(
        "OCTOPUS_KB_VAULTS",
        json.dumps({"vault-1": {"root": str(root), "allowed_access_labels": ["internal"]}}),
    )
    return root


def test_scan_and_active_view_skip_escaping_leaves_before_read(vault):
    with pytest.raises(VaultRootError):
        load_page(vault / "wiki" / "link.md", root=vault)
    with pytest.raises(VaultRootError):
        load_page(vault / ".octopus-kb" / "revisions" / "rev-one" / "leaked.md", root=vault)

    scanned = "\n".join(page.body for page in scan_markdown_files(vault))
    assert SECRET not in scanned
    assert "inside body stays" in scanned

    view = load_view(vault)
    rendered = json.dumps({"pages": [page.body for page in view.pages], "text": view.text_by_path})
    assert SECRET not in rendered
    assert "managed inside stays" in rendered
    assert any(page.path == "wiki/alias.md" and "inside body stays" in page.body for page in view.pages)


def test_retrieve_export_lookup_neighbors_and_propose_hide_escaping_bytes(vault, monkeypatch):
    sys.path.insert(0, str(MCP_ROOT))
    from octopus_kb_mcp import tools

    retrieved = tools.retrieve_bundle(vault, SECRET)
    retrieved.pop("query", None)
    exported = tools.export_graph(vault)
    looked_up = tools.lookup(vault, SECRET)
    looked_up.pop("term", None)
    neighbors = tools.neighbors(vault, "wiki/index.md")
    store = ObsidianStore(vault)
    published = json.dumps({
        "retrieve": retrieved,
        "export": exported,
        "lookup": looked_up,
        "neighbors": neighbors,
        "bodies": [page.body for page in store.list_page_records()],
        "text": store.view().text_by_path,
    })
    assert SECRET not in published
    assert "inside body stays" in published
    assert "managed inside stays" in published

    try:
        leaf_neighbors = compute_neighbors("wiki/link.md", vault).to_dict()
    except ValueError as exc:
        assert "Page not found" in str(exc)
        leaf_neighbors = {}
    assert SECRET not in json.dumps(leaf_neighbors)

    with pytest.raises(VaultRootError):
        tools.neighbors(vault, "wiki/link.md")
    with pytest.raises(VaultRootError):
        tools.propose(vault, "wiki/link.md")

    captured: list[str] = []

    def _capture(self, req, **_kwargs):
        captured.append(json.dumps(req.messages))
        raise LLMError("stop-before-network")

    monkeypatch.setattr(ChatClient, "chat", _capture)
    with pytest.raises(ProposeRuntimeError, match="stop-before-network"):
        propose_from_raw(vault / "raw" / "source.md", vault)
    assert captured
    assert SECRET not in captured[0]
