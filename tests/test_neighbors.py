import io
import json
import sys
from pathlib import Path


def _seed_vault(root: Path) -> None:
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "raw").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (root / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "RAG Operations.md").write_text(
        '---\ntitle: "RAG Operations"\ntype: concept\nlang: en\n'
        'role: concept\nlayer: wiki\nsource_of_truth: canonical\n'
        'tags: []\nsummary: "s"\naliases:\n  - "RAG Ops"\n'
        'related_entities:\n  - "Vector Store"\n---\n'
        'See [[Knowledge Graph]].\n',
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Vector Store.md").write_text(
        '---\ntitle: "Vector Store"\ntype: entity\nlang: en\nrole: entity\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    (root / "wiki" / "entities" / "Knowledge Graph.md").write_text(
        '---\ntitle: "Knowledge Graph"\ntype: entity\nlang: en\nrole: entity\n'
        'layer: wiki\nsource_of_truth: canonical\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )
    (root / "raw" / "src.md").write_text(
        '---\ntitle: "src"\ntype: raw_source\nlang: en\nrole: raw_source\n'
        'layer: source\ntags: []\n---\n'
        'Inbound: [[RAG Operations]] [[RAG Operations]].\n',
        encoding="utf-8",
    )


def test_cli_neighbors_returns_inbound_outbound_aliases(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(
            [
                "neighbors",
                "wiki/concepts/RAG Operations.md",
                "--vault",
                str(vault),
                "--json",
            ]
        )
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["page"] == "wiki/concepts/RAG Operations.md"

    inbound_paths = {i["path"]: i for i in data["inbound"]}
    assert "raw/src.md" in inbound_paths
    assert inbound_paths["raw/src.md"]["count"] == 2

    outbound_pairs = {(o["path"], o["via"]) for o in data["outbound"]}
    assert ("wiki/entities/Vector Store.md", "related_entities") in outbound_pairs
    assert ("wiki/entities/Knowledge Graph.md", "wikilink") in outbound_pairs

    assert "RAG Ops" in data["aliases"]
    assert data["canonical_identity"] == "rag operations"


def test_neighbors_output_matches_schema(tmp_path):
    import jsonschema

    vault = tmp_path / "vault"
    _seed_vault(vault)

    schema_path = (
        Path(__file__).resolve().parent.parent / "schemas" / "cli" / "neighbors.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        main(
            [
                "neighbors",
                "wiki/concepts/RAG Operations.md",
                "--vault",
                str(vault),
                "--json",
            ]
        )
    finally:
        sys.stdout = original

    jsonschema.validate(json.loads(buf.getvalue()), schema)


def test_cli_neighbors_rejects_path_outside_vault(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    outside = tmp_path / "outside.md"
    outside.write_text(
        '---\ntitle: "x"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    rc = main(["neighbors", str(outside.resolve()), "--vault", str(vault), "--json"])
    assert rc == 2


def test_cli_neighbors_returns_empty_when_page_has_no_links(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Schema\n", encoding="utf-8")
    (vault / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (vault / "wiki" / "LOG.md").write_text("# Log\n", encoding="utf-8")
    (vault / "wiki" / "orphan.md").write_text(
        '---\ntitle: "orphan"\ntype: concept\nlang: en\nrole: concept\n'
        'layer: wiki\ntags: []\nsummary: "s"\n---\n',
        encoding="utf-8",
    )

    from octopus_kb_compound.cli import main

    buf = io.StringIO()
    original = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["neighbors", "wiki/orphan.md", "--vault", str(vault), "--json"])
    finally:
        sys.stdout = original

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["inbound"] == []
    assert data["outbound"] == []
