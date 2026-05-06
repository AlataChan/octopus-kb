from __future__ import annotations

from pathlib import Path


def _seed_store_vault(root: Path) -> None:
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "RAG Operations.md").write_text(
        '---\ntitle: "RAG Operations"\ntype: concept\nlang: en\n'
        'role: concept\nlayer: wiki\nsource_of_truth: canonical\n'
        'aliases:\n  - "RAG Ops"\ntags: []\nsummary: "Ops wrapper."\n---\n'
        "# RAG Operations\n",
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Vector Store.md").write_text(
        '---\ntitle: "Vector Store"\ntype: entity\nlang: en\n'
        'role: entity\nlayer: wiki\nsource_of_truth: canonical\n'
        'tags: []\nsummary: "Entity."\n---\n',
        encoding="utf-8",
    )


def test_obsidian_store_lists_reads_and_resolves_aliases(tmp_path: Path):
    from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
    from octopus_kb_compound.ckr.models import CanonicalRef, StorageRef

    _seed_store_vault(tmp_path)
    store = ObsidianStore(tmp_path)

    pages = store.list_pages()
    assert [page.storage.locator for page in pages] == [
        "wiki/LOG.md",
        "wiki/concepts/RAG Operations.md",
        "wiki/entities/Vector Store.md",
    ]

    by_storage = store.read_page(
        StorageRef(adapter="obsidian", locator="wiki/concepts/RAG Operations.md")
    )
    assert by_storage.title == "RAG Operations"

    by_ref = store.read_page(CanonicalRef(id="ragoperations", kind="concept"))
    assert by_ref.storage.locator == "wiki/concepts/RAG Operations.md"

    resolved = store.resolve_alias("RAG Ops")
    assert resolved == by_ref.ref


def test_obsidian_store_prepares_and_applies_safe_ops(tmp_path: Path):
    from octopus_kb_compound.adapters.obsidian.store import ObsidianStore
    from octopus_kb_compound.ckr.models import CanonicalPage, CanonicalRef, StorageRef
    from octopus_kb_compound.ckr.operations import AddAliasOp, AppendLogOp, CreatePageOp

    _seed_store_vault(tmp_path)
    store = ObsidianStore(tmp_path)
    new_page = CanonicalPage(
        ref=CanonicalRef(id="latechunking", kind="concept", title="Late Chunking"),
        title="Late Chunking",
        kind="concept",
        language="en",
        body="# Late Chunking\n",
        storage=StorageRef(adapter="obsidian", locator="wiki/concepts/Late Chunking.md"),
        metadata={
            "title": "Late Chunking",
            "type": "concept",
            "lang": "en",
            "role": "concept",
            "layer": "wiki",
            "summary": "Chunking after token context.",
        },
    )
    ops = [
        CreatePageOp(page=new_page, rationale="new concept", confidence=0.9),
        AddAliasOp(
            target=StorageRef(adapter="obsidian", locator="wiki/concepts/RAG Operations.md"),
            alias="RAG runbook",
            rationale="source term",
            confidence=0.9,
        ),
        AppendLogOp(
            target=StorageRef(adapter="obsidian", locator="wiki/LOG.md"),
            entry="- Added CKR store test.",
            rationale="log update",
            confidence=1.0,
        ),
    ]

    prepared = store.prepare_ops(ops)

    assert [ref.locator for ref in prepared.created] == ["wiki/concepts/Late Chunking.md"]
    assert [ref.locator for ref in prepared.modified] == [
        "wiki/LOG.md",
        "wiki/concepts/RAG Operations.md",
    ]

    receipt = store.apply_ops(ops, prepared=prepared)

    assert [ref.locator for ref in receipt.created] == ["wiki/concepts/Late Chunking.md"]
    assert "Late Chunking" in (tmp_path / "wiki" / "concepts" / "Late Chunking.md").read_text(encoding="utf-8")
    assert "RAG runbook" in (tmp_path / "wiki" / "concepts" / "RAG Operations.md").read_text(encoding="utf-8")
    assert "Added CKR store test" in (tmp_path / "wiki" / "LOG.md").read_text(encoding="utf-8")

